PROJECT(kungfu-extensions)

############################################################

INCLUDE_DIRECTORIES(${CMAKE_SOURCE_DIR}/cpp/yijinjing/include)
INCLUDE_DIRECTORIES(${CMAKE_SOURCE_DIR}/cpp/wingchun/include)

ADD_SUBDIRECTORY(binance)
