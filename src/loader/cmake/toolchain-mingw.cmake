set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)

set(TOOLCHAIN_PREFIX x86_64-w64-mingw32)

# Prefer the posix-thread-model compilers when the distro ships both variants.
# Ubuntu 22.04's default alternative is the win32 model, whose GCC 10 libstdc++
# has no std::thread/std::mutex (GCC >= 13 supports them under either model, so
# Debian 13's default works unmodified). winpthreads is covered by -static.
find_program(MINGW_GCC_POSIX ${TOOLCHAIN_PREFIX}-gcc-posix)
find_program(MINGW_GXX_POSIX ${TOOLCHAIN_PREFIX}-g++-posix)
if(MINGW_GCC_POSIX AND MINGW_GXX_POSIX)
    set(CMAKE_C_COMPILER   ${MINGW_GCC_POSIX})
    set(CMAKE_CXX_COMPILER ${MINGW_GXX_POSIX})
else()
    set(CMAKE_C_COMPILER   ${TOOLCHAIN_PREFIX}-gcc)
    set(CMAKE_CXX_COMPILER ${TOOLCHAIN_PREFIX}-g++)
endif()
set(CMAKE_RC_COMPILER  ${TOOLCHAIN_PREFIX}-windres)

set(CMAKE_FIND_ROOT_PATH /usr/${TOOLCHAIN_PREFIX})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
