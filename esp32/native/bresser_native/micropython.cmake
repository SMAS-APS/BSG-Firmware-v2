add_library(usermod_bresser_native INTERFACE)

target_sources(usermod_bresser_native INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/bresser_decoder.cpp
    ${CMAKE_CURRENT_LIST_DIR}/sx1276_receiver.cpp
    ${CMAKE_CURRENT_LIST_DIR}/modbresser_native.cpp
)

target_include_directories(usermod_bresser_native INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_compile_features(usermod_bresser_native INTERFACE cxx_std_17)

# MicroPython recenti usano componenti ESP-IDF separati per GPIO e SPI.
# I controlli TARGET mantengono la configurazione utilizzabile anche con IDF
# precedenti, dove tali dipendenze arrivavano dal componente "driver".
foreach(idf_component esp_driver_gpio esp_driver_spi esp_timer driver)
    if(TARGET idf::${idf_component})
        target_link_libraries(usermod_bresser_native INTERFACE idf::${idf_component})
    endif()
endforeach()

target_link_libraries(usermod INTERFACE usermod_bresser_native)
