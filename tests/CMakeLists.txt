cmake_minimum_required(VERSION 3.16)
project(bresser_decoder_tests LANGUAGES CXX)

enable_testing()

add_executable(test_bresser_decoder
    test_decoder.cpp
    ../native/bresser_native/bresser_decoder.cpp
)

target_include_directories(test_bresser_decoder PRIVATE
    ../native/bresser_native
)

target_compile_features(test_bresser_decoder PRIVATE cxx_std_17)

if(MSVC)
    target_compile_options(test_bresser_decoder PRIVATE /W4 /WX)
else()
    target_compile_options(test_bresser_decoder PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_test(NAME bresser_decoder COMMAND test_bresser_decoder)
