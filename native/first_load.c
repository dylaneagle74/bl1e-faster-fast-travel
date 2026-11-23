#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdatomic.h>
#include <stdint.h>
#include <wchar.h>

typedef HANDLE (WINAPI *CreateFileWFn)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES,
                                 DWORD, DWORD, HANDLE);

enum { ENTRY_COUNT = 2048, MAX_LOOKUP_PATH = 512, PROBE_LIMIT = 12 };
/* Return address of the package reader's CreateFileW import call, Enhanced 9171464. */
static const uintptr_t package_open_return = 0xF1404;

static struct MissingFile {
    uint64_t hash;
    uint32_t generation;
    DWORD error;
    wchar_t name[MAX_LOOKUP_PATH];
} missing[ENTRY_COUNT];
static CreateFileWFn original_open;
static void **import_slot;
static uintptr_t game_base;
static wchar_t game_root[MAX_LOOKUP_PATH];
static int root_length;
static _Atomic DWORD game_thread;
static uint32_t generation;
static unsigned checks, reused;

static BOOL is_package_probe(const wchar_t *name, wchar_t *path) {
    DWORD size = GetFullPathNameW(name, MAX_LOOKUP_PATH, path, NULL);
    if (!size || size >= MAX_LOOKUP_PATH || size <= (DWORD)root_length
        || CompareStringOrdinal(path, root_length, game_root, root_length, TRUE) != CSTR_EQUAL)
        return FALSE;
    if (wcsstr(path + root_length, L"\\Localization\\"))
        return TRUE;
    /* A bare package name is also used by the engine's file lookup. */
    return name[0] && !wcspbrk(name, L"\\/:");
}

static uint64_t hash_path(const wchar_t *name) {
    uint64_t hash = UINT64_C(14695981039346656037);
    while (*name)
        hash = (hash ^ (uint16_t)*name++) * UINT64_C(1099511628211);
    return hash;
}

static struct MissingFile *find_entry(const wchar_t *path, uint64_t hash) {
    unsigned index = (unsigned)hash & (ENTRY_COUNT - 1);
    for (unsigned i = 0; i < PROBE_LIMIT; i++, index = (index + 1) & (ENTRY_COUNT - 1)) {
        struct MissingFile *entry = &missing[index];
        if (entry->generation != generation || (entry->hash == hash && !wcscmp(entry->name, path)))
            return entry;
    }
    return NULL;
}

static HANDLE WINAPI open_package(LPCWSTR name, DWORD access, DWORD share,
                                  LPSECURITY_ATTRIBUTES security, DWORD disposition,
                                  DWORD flags, HANDLE template) {
    DWORD owner = atomic_load_explicit(&game_thread, memory_order_relaxed);
    if (!owner || GetCurrentThreadId() != owner
        || (uintptr_t)__builtin_return_address(0) - game_base != package_open_return
        || access != GENERIC_READ || disposition != OPEN_EXISTING
        || flags != FILE_ATTRIBUTE_NORMAL || security || template || !name) {
        return original_open(name, access, share, security, disposition, flags, template);
    }

    wchar_t path[MAX_LOOKUP_PATH];
    DWORD original_error = GetLastError();
    if (!is_package_probe(name, path)) {
        SetLastError(original_error);
        return original_open(name, access, share, security, disposition, flags, template);
    }
    checks++;
    uint64_t hash = hash_path(path);
    struct MissingFile *entry = find_entry(path, hash);
    if (entry && entry->generation == generation) {
        reused++;
        SetLastError(entry->error);
        return INVALID_HANDLE_VALUE;
    }

    SetLastError(original_error);
    HANDLE file = original_open(name, access, share, security, disposition, flags, template);
    DWORD error = GetLastError();
    if (entry && file == INVALID_HANDLE_VALUE && (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND)) {
        entry->hash = hash;
        entry->error = error;
        wcscpy(entry->name, path);
        entry->generation = generation;
    }
    SetLastError(error);
    return file;
}

static void **find_create_file_import(unsigned char *base) {
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return NULL;
    IMAGE_NT_HEADERS64 *image = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (image->Signature != IMAGE_NT_SIGNATURE || image->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC)
        return NULL;
    DWORD rva = image->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva)
        return NULL;
    for (IMAGE_IMPORT_DESCRIPTOR *dll = (IMAGE_IMPORT_DESCRIPTOR *)(base + rva); dll->Name; dll++) {
        if (!dll->OriginalFirstThunk || lstrcmpiA((const char *)(base + dll->Name), "kernel32.dll"))
            continue;
        IMAGE_THUNK_DATA64 *symbol = (IMAGE_THUNK_DATA64 *)(base + dll->OriginalFirstThunk);
        void **slot = (void **)(base + dll->FirstThunk);
        for (; symbol->u1.AddressOfData; symbol++, slot++) {
            if (IMAGE_SNAP_BY_ORDINAL64(symbol->u1.Ordinal))
                continue;
            IMAGE_IMPORT_BY_NAME *named = (IMAGE_IMPORT_BY_NAME *)(base + symbol->u1.AddressOfData);
            if (!lstrcmpA((const char *)named->Name, "CreateFileW"))
                return slot;
        }
    }
    return NULL;
}

__declspec(dllexport) BOOL first_load_install(void) {
    if (import_slot)
        return *import_slot == (void *)open_package;
    DWORD size = GetModuleFileNameW(NULL, game_root, MAX_LOOKUP_PATH);
    if (!size || size >= MAX_LOOKUP_PATH)
        return FALSE;
    static const wchar_t binary_suffix[] = L"\\Binaries\\Win64\\BorderlandsGOTY.exe";
    int suffix_length = (int)(sizeof(binary_suffix) / sizeof(binary_suffix[0]) - 1);
    if (size <= (DWORD)suffix_length
        || CompareStringOrdinal(game_root + size - suffix_length, suffix_length,
                                binary_suffix, suffix_length, TRUE) != CSTR_EQUAL)
        return FALSE;
    root_length = (int)size - suffix_length + 1;
    game_root[root_length] = L'\0';
    game_base = (uintptr_t)GetModuleHandleW(NULL);
    void **slot = find_create_file_import((unsigned char *)game_base);
    if (!slot)
        return FALSE;
    HMODULE pinned;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                            (LPCWSTR)open_package, &pinned))
        return FALSE;
    DWORD old;
    if (!VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old))
        return FALSE;
    original_open = (CreateFileWFn)*slot;
    InterlockedExchangePointer(slot, (void *)open_package);
    VirtualProtect(slot, sizeof(*slot), old, &old);
    import_slot = slot;
    return TRUE;
}

__declspec(dllexport) void first_load_begin(void) {
    atomic_store_explicit(&game_thread, 0, memory_order_relaxed);
    if (!import_slot || *import_slot != (void *)open_package)
        return;
    if (++generation == 0) {
        ZeroMemory(missing, sizeof(missing));
        generation = 1;
    }
    checks = reused = 0;
    atomic_store_explicit(&game_thread, GetCurrentThreadId(), memory_order_relaxed);
}

__declspec(dllexport) uint64_t first_load_end(void) {
    atomic_store_explicit(&game_thread, 0, memory_order_relaxed);
    return ((uint64_t)checks << 32) | reused;
}

__declspec(dllexport) void first_load_remove(void) {
    first_load_end();
    if (!import_slot)
        return;
    DWORD old;
    if (!VirtualProtect(import_slot, sizeof(*import_slot), PAGE_READWRITE, &old))
        return;
    void *prior = InterlockedCompareExchangePointer(import_slot, (void *)original_open, (void *)open_package);
    VirtualProtect(import_slot, sizeof(*import_slot), old, &old);
    if (prior == (void *)open_package)
        import_slot = NULL;
}
