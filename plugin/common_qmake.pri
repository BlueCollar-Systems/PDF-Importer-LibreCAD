# Shared qmake settings for the BlueCollar LibreCAD plugin builds.
#
# Keep this minimal and avoid forcing compilers so the selected Qt kit
# (msvc2019_64) controls ABI compatibility.

isEmpty(GENERATED_DIR) {
    GENERATED_DIR = $$OUT_PWD/generated
}

OBJECTS_DIR = $${GENERATED_DIR}/obj
MOC_DIR = $${GENERATED_DIR}/moc
RCC_DIR = $${GENERATED_DIR}/rcc
UI_DIR = $${GENERATED_DIR}/ui

win32-msvc* {
    # Reproducible binaries: the release gate re-builds the portable ZIP and
    # requires byte-identical output, so no link timestamps / random GUIDs.
    QMAKE_CFLAGS += /Brepro
    QMAKE_CXXFLAGS += /Brepro /utf-8
    QMAKE_LFLAGS += /Brepro
    QMAKE_LFLAGS_RELEASE -= /DEBUG
}
