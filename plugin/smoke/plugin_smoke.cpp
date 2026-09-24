// SPDX-License-Identifier: GPL-2.0-or-later
// Loads bc_lcpdf_menu.dll exactly the way LibreCAD 2.2.x does (QPluginLoader +
// qobject_cast<QC_PluginInterface*>), checks the menu entries, and optionally
// runs the full Import PDF handoff against a fake importer.
//
// usage: plugin_smoke <plugin.dll> [--e2e <python.exe> <fake_importer.py> <expected.dxf>]

#include "plugin_smoke.h"

#include "../sdk/qc_plugininterface.h"

#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QPluginLoader>
#include <QTextStream>
#include <QTimer>

static int fail(const QString &message) {
    QTextStream(stderr) << "PLUGIN SMOKE FAIL: " << message << "\n";
    return 1;
}

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    const QStringList args = app.arguments();
    if (args.size() < 2) {
        return fail("usage: plugin_smoke <plugin.dll> [--e2e <python> <fake_importer.py> <expected.dxf>]");
    }

    QPluginLoader loader(QFileInfo(args.at(1)).absoluteFilePath());
    const QString iid = loader.metaData().value("IID").toString();
    if (iid != QStringLiteral("org.librecad.PluginInterface/1.0")) {
        return fail("unexpected IID: " + iid);
    }
    QObject *instance = loader.instance();
    if (instance == nullptr) {
        return fail("QPluginLoader could not load plugin: " + loader.errorString());
    }
    auto *plugin = qobject_cast<QC_PluginInterface *>(instance);
    if (plugin == nullptr) {
        return fail("plugin does not implement QC_PluginInterface");
    }

    const QStringList expected = {
        QStringLiteral("plugins_menu|Import PDF (BlueCollar)..."),
        QStringLiteral("plugins_menu|Import PDF into Current Drawing (BlueCollar)..."),
        QStringLiteral("plugins_menu|PDF Importer Settings (BlueCollar)..."),
        QStringLiteral("tools_menu|Import PDF (BlueCollar)..."),
    };
    QStringList actual;
    for (const PluginMenuLocation &loc : plugin->getCapabilities().menuEntryPoints) {
        actual << loc.menuEntryPoint + "|" + loc.menuEntryActionName;
    }
    // Element-wise: QList::operator== trips a removed MSVC STL helper in Qt 5.15 headers.
    bool same = actual.size() == expected.size();
    for (int i = 0; same && i < actual.size(); ++i) {
        same = actual.at(i) == expected.at(i);
    }
    if (!same) {
        return fail("unexpected menu entries: " + actual.join(" ; "));
    }
    QTextStream(stdout) << "plugin loaded: " << plugin->name() << "\n"
                        << "menu: " << actual.join(" ; ") << "\n";

    if (args.size() >= 6 && args.at(2) == QStringLiteral("--e2e")) {
        const QString python = args.at(3);
        const QString fakeImporter = QFileInfo(args.at(4)).absoluteFilePath();
        const QString expectedDxf = QFileInfo(args.at(5)).absoluteFilePath();
        qputenv("BC_LC_IMPORTER_SCRIPT", fakeImporter.toUtf8());
        qputenv("BC_LC_IMPORTER_PYTHON", python.toUtf8());
        // Environment variables are 8-bit in Qt 5 on Windows, so hand the
        // (deliberately non-ASCII) DXF path to the fake importer via a UTF-8 file.
        QFile target(QDir(QDir::tempPath()).filePath("bc_fake_importer_target.txt"));
        if (!target.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            return fail("cannot write fake importer target file");
        }
        target.write(expectedDxf.toUtf8());
        target.close();

        FakeLibreCadWindow window;
        window.show();
        plugin->execComm(nullptr, &window, QStringLiteral("Import PDF (BlueCollar)..."));

        QElapsedTimer clock;
        clock.start();
        while (window.openedPath.isEmpty() && clock.elapsed() < 30000) {
            app.processEvents(QEventLoop::AllEvents, 100);
        }
        if (window.openedPath.isEmpty()) {
            return fail("plugin never asked LibreCAD to open the converted DXF");
        }
        if (QDir::cleanPath(QDir::fromNativeSeparators(window.openedPath))
                .compare(QDir::cleanPath(expectedDxf), Qt::CaseInsensitive) != 0) {
            return fail("plugin opened the wrong file: " + window.openedPath);
        }
        QTextStream(stdout) << "e2e handoff opened: " << window.openedPath << "\n";
    }

    QTextStream(stdout) << "PLUGIN SMOKE OK\n";
    return 0;
}
