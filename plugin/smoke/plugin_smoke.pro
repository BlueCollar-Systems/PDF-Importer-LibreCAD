# Test harness only - never shipped.
QT += widgets
TEMPLATE = app
CONFIG += console c++17 release
CONFIG -= app_bundle debug debug_and_release
TARGET = plugin_smoke
isEmpty(BC_PLUGIN_OUT) {
    BC_PLUGIN_OUT = $$OUT_PWD/out
}
DESTDIR = $$BC_PLUGIN_OUT
GENERATED_DIR = $$OUT_PWD/generated
include(../common_qmake.pri)
INCLUDEPATH += ../sdk
SOURCES += plugin_smoke.cpp
HEADERS += plugin_smoke.h ../sdk/qc_plugininterface.h
