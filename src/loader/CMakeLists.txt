cmake_minimum_required(VERSION 3.16)
project(RavenswatchModManager LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

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
target_include_directories(lua54 PUBLIC ${TP}/lua)
target_compile_definitions(lua54 PUBLIC LUA_USE_WINDOWS=1)

# --- Loader DLL ----------------------------------------------------------
# In-game UI (hook_vk + hook_win32 + ImGui) removed: surface was never
# feature-complete. The loader is now just asset-overrides (hook_io),
# Lua VM (script_lua), and the generic hook bridge (hook_lua) that
# backs the public rsmm.hook API.
set(LOADER_SRC
    src/dllmain.cpp
    src/loader.cpp
    src/hook_io.cpp
    src/hook_engine.cpp
    src/hook_lua.cpp
    src/script_lua.cpp
    src/fn_resolver.cpp
    src/fn_call.cpp
    src/tls_callback.cpp)

add_library(winhttp SHARED
    ${LOADER_SRC}
    exports/winhttp.def)

target_include_directories(winhttp PRIVATE
    include
    ${TP}/nlohmann
    ${TP}/tomlplusplus)

if(MSVC)
  find_library(WINHTTP_SYSTEM_LIB winhttp)
  target_link_libraries(winhttp PRIVATE
      minhook
      lua54
      "${WINHTTP_SYSTEM_LIB}" kernel32 user32 gdi32 psapi ole32)
else()
  target_link_libraries(winhttp PRIVATE
      minhook
      lua54
      -static -static-libgcc -static-libstdc++
      -lwinhttp -lkernel32 -luser32 -lgdi32 -lpsapi -lole32)
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
