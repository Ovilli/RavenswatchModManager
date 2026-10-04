cmake_minimum_required(VERSION 3.16)
project(RavenswatchModManager LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Target Windows 7+ explicitly. Old mingw-w64 headers (Ubuntu 22.04 / GCC 10)
# default _WIN32_WINNT to XP, which hides Vista+ APIs like GetTickCount64.
add_compile_definitions(_WIN32_WINNT=0x0601 WINVER=0x0601)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
  add_compile_options(-Wall -Wno-unused-function -Wno-unused-variable -Wno-cast-function-type)
elseif(MSVC)
  add_compile_options(/W3)
endif()

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
# SYSTEM: its headers' own warnings (luaconf.h) are upstream's, not ours, and
# would otherwise surface inside every loader file that includes lua.h.
target_include_directories(lua54 SYSTEM PUBLIC ${TP}/lua)
# No LUA_USE_WINDOWS here: luaconf.h defines it itself whenever _WIN32 is set
# (MinGW and MSVC both set it), and a second definition with a value is a
# redefinition warning in every file that includes lua.h.

# --- Loader DLL ----------------------------------------------------------
# In-game UI (hook_vk + hook_win32 + ImGui) removed: surface was never
# feature-complete. The loader is now just asset-overrides (hook_io),
# Lua VM (script_lua), and the generic hook bridge (hook_lua) that
# backs the public rsmm.hook API.
set(LOADER_SRC
    src/dllmain.cpp
    src/loader.cpp
    src/mem_safe.cpp
    src/health.cpp
    src/hook_io.cpp
    src/hook_engine.cpp
    src/hook_skins.cpp
    src/hook_skills.cpp
    src/hook_ui.cpp
    src/hook_items.cpp
    src/hook_rewards.cpp
    src/hook_resource.cpp
    src/hook_levelload.cpp
    src/hook_levelbuild.cpp
    src/hook_events.cpp
    src/hook_gamevalues.cpp
    src/hook_netcode.cpp
    src/hook_backend.cpp
    src/hook_lua.cpp
    src/script_lua.cpp
    src/hook_util.cpp
    src/watchpoint.cpp
    src/fn_resolver.cpp
    src/fn_call.cpp)

add_library(winhttp SHARED
    ${LOADER_SRC}
    exports/winhttp.def)

target_include_directories(winhttp PRIVATE include)
target_include_directories(winhttp SYSTEM PRIVATE
    ${TP}/nlohmann
    ${TP}/tomlplusplus)

# Stricter than the vendored code gets: the loader's own C++ builds clean under
# these (2026-09-26), so a new warning here is a new problem, not noise.
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
  target_compile_options(winhttp PRIVATE -Wextra -Wshadow)
endif()

if(MSVC)
  target_link_libraries(winhttp PRIVATE
      minhook
      lua54
      kernel32 user32 gdi32 psapi ole32)
else()
  target_link_libraries(winhttp PRIVATE
      minhook
      lua54
      -static -static-libgcc -static-libstdc++
      -lkernel32 -luser32 -lgdi32 -lpsapi -lole32)
endif()

if(MSVC)
  set_target_properties(winhttp PROPERTIES
      PREFIX ""
      OUTPUT_NAME "winhttp"
      SUFFIX ".dll")
else()
  set_target_properties(winhttp PROPERTIES
      PREFIX ""
      OUTPUT_NAME "winhttp"
      SUFFIX ".dll"
      LINK_FLAGS "-Wl,--enable-stdcall-fixup")
endif()

install(TARGETS winhttp RUNTIME DESTINATION dist)
