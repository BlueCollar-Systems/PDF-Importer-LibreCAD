# BlueCollar PDF Importer menu plugin for LibreCAD 2.2.x.
# Must be built with the same Qt major/minor kit and MSVC runtime family as the
# target LibreCAD (LibreCAD 2.2.1.x Windows = Qt 5.15.2 msvc2019_64, release).
QT += widgets
TEMPLATE = lib
CONFIG += plugin c++17 release
CONFIG -= debug debug_and_release
# No VERSION: keeps the file name stable as bc_lcpdf_menu.dll.
TARGET = bc_lcpdf_menu

isEmpty(BC_PLUGIN_OUT) {
    BC_PLUGIN_OUT = $$OUT_PWD/out
}
DESTDIR = $$BC_PLUGIN_OUT

GENERATED_DIR = $$OUT_PWD/generated
include(../common_qmake.pri)

INCLUDEPATH += ../sdk

SOURCES += lcpdf_menu.cpp
HEADERS += lcpdf_menu.h ../sdk/qc_plugininterface.h ../sdk/document_interface.h
DISTFILES += lcpdf_menu.json
