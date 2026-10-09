cmake_minimum_required(VERSION 3.22)
project(lucent_lsfg_qualification LANGUAGES C CXX)

if(NOT ANDROID OR NOT ANDROID_ABI STREQUAL "arm64-v8a")
    message(FATAL_ERROR "LSFG qualification host is Android arm64-v8a only")
endif()
if(NOT DEFINED LSFG_WRAPPER_DIR OR NOT EXISTS "${LSFG_WRAPPER_DIR}/framegen/CMakeLists.txt")
    message(FATAL_ERROR "LSFG_WRAPPER_DIR must name the verified pinned public wrapper")
endif()

add_subdirectory("${LSFG_WRAPPER_DIR}/thirdparty/volk" volk EXCLUDE_FROM_ALL)
add_subdirectory("${LSFG_WRAPPER_DIR}/framegen" framegen EXCLUDE_FROM_ALL)
target_compile_definitions(volk PUBLIC VK_USE_PLATFORM_ANDROID_KHR=1)
target_compile_definitions(lsfg-vk-framegen PUBLIC VK_USE_PLATFORM_ANDROID_KHR=1)

add_library(lucent_lsfg_qualification SHARED
    lsfg_qualification_jni.cpp
    owned_surface_control_presenter.cpp
    triplet_capture.cpp
    owned_vulkan_host.cpp)
set_target_properties(lucent_lsfg_qualification PROPERTIES
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED ON)
target_compile_definitions(lucent_lsfg_qualification PRIVATE
    VK_NO_PROTOTYPES=1
    EMUFUSION_LSFG_PIXEL_PROBE=$<BOOL:${EMUFUSION_LSFG_PIXEL_PROBE}>
    LUCENT_LSFG_WRAPPER_COMMIT="3e89e5439a98f55d5acb003d20039426ab24e69c")
target_include_directories(lucent_lsfg_qualification PRIVATE
    "${LSFG_WRAPPER_DIR}/framegen/public"
    "${LSFG_WRAPPER_DIR}/thirdparty/volk")
target_link_libraries(lucent_lsfg_qualification PRIVATE
    lsfg-vk-framegen android log dl sync vulkan)
target_link_options(lucent_lsfg_qualification PRIVATE
    "-Wl,-z,max-page-size=16384"
    "-Wl,-z,common-page-size=16384")
