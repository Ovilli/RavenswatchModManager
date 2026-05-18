cmake_minimum_required(VERSION 3.16)
project(RavenswatchModManager LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_compile_options(-Wall -Wno-unused-function -Wno-unused-variable -Wno-cast-function-type)

set(TP ${CMAKE_CURRENT_SOURCE_DIR}/third_party)

# --- MinHook -------------------------------------------------------------
file(GLOB MINHOOK_SRC
    ${TP}/minhook/src/*.c
    ${TP}/minhook/src/hde/*.c)
add_library(minhook STATIC ${MINHOOK_SRC})
target_include_directories(minhook PUBLIC
    ${TP}/minhook/include
    ${TP}/minhook/src
    ${TP}/minhook/src/hde)

# --- Lua 5.4 -------------------------------------------------------------
file(GLOB LUA_SRC ${TP}/lua/*.c)
list(FILTER LUA_SRC EXCLUDE REGEX ".*/lua\\.c$")
list(FILTER LUA_SRC EXCLUDE REGEX ".*/luac\\.c$")
list(FILTER LUA_SRC EXCLUDE REGEX ".*/ltests\\.c$")
list(FILTER LUA_SRC EXCLUDE REGEX ".*/onelua\\.c$")
add_library(lua54 STATIC ${LUA_SRC})
target_include_directories(lua54 PUBLIC ${TP}/lua)
target_compile_definitions(lua54 PUBLIC LUA_USE_WINDOWS=1)

# --- ImGui core + backends ----------------------------------------------
set(IMGUI ${TP}/imgui)
set(IMGUI_SRC
    ${IMGUI}/imgui.cpp
    ${IMGUI}/imgui_draw.cpp
    ${IMGUI}/imgui_tables.cpp
    ${IMGUI}/imgui_widgets.cpp
    ${IMGUI}/imgui_demo.cpp
    ${IMGUI}/backends/imgui_impl_vulkan.cpp
    ${IMGUI}/backends/imgui_impl_win32.cpp)
add_library(imgui STATIC ${IMGUI_SRC})
target_include_directories(imgui PUBLIC ${IMGUI} ${IMGUI}/backends ${TP}/Vulkan-Headers/include)
target_compile_definitions(imgui PUBLIC
    VK_USE_PLATFORM_WIN32_KHR=1
    VK_NO_PROTOTYPES=1
    IMGUI_IMPL_VULKAN_NO_PROTOTYPES=1)

# --- Loader DLL ----------------------------------------------------------
set(LOADER_SRC
    src/dllmain.cpp
    src/loader.cpp
    src/hook_io.cpp
    src/hook_vk.cpp
    src/hook_win32.cpp
    src/hook_engine.cpp
    src/hook_lua.cpp
    src/script_lua.cpp
    src/fn_resolver.cpp
    src/fn_call.cpp)

add_library(winhttp SHARED
    ${LOADER_SRC}
    exports/winhttp.def)

target_include_directories(winhttp PRIVATE
    include
    ${TP}/nlohmann
    ${TP}/tomlplusplus
    ${TP}/Vulkan-Headers/include
    ${IMGUI}
    ${IMGUI}/backends)

target_compile_definitions(winhttp PRIVATE
    VK_USE_PLATFORM_WIN32_KHR=1
    VK_NO_PROTOTYPES=1
    IMGUI_IMPL_VULKAN_NO_PROTOTYPES=1)

target_link_libraries(winhttp PRIVATE
    minhook
    imgui
    lua54
    -static -static-libgcc -static-libstdc++
    -lkernel32 -luser32 -lgdi32 -lpsapi -lole32 -ldwmapi -limm32)

set_target_properties(winhttp PROPERTIES
    PREFIX ""
    OUTPUT_NAME "winhttp"
    SUFFIX ".dll"
    LINK_FLAGS "-Wl,--enable-stdcall-fixup")

install(TARGETS winhttp RUNTIME DESTINATION dist)
