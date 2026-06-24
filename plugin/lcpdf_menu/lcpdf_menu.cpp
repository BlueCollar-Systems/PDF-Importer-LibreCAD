#include "lcpdf_menu.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QMessageBox>
#include <QProcess>
#include <QSettings>
#include <QStandardPaths>
#include <QStringList>

namespace {

const char *kActionLaunch = "PDF Importer (BlueCollar)...";
const char *kActionSettings = "PDF Importer Settings...";

QStringList candidateScripts() {
    QStringList candidates;

    const QString envScript = qEnvironmentVariable("BC_LC_IMPORTER_SCRIPT");
    if (!envScript.trimmed().isEmpty()) {
        candidates << QDir::fromNativeSeparators(envScript);
    }

    const QString appDir = QCoreApplication::applicationDirPath();
    candidates
        << QDir::cleanPath(appDir + "/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(appDir + "/gui.py")
        << QDir::cleanPath(appDir + "/../launch_lcpdf_gui.pyw")
        << QDir::cleanPath(appDir + "/../gui.py")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer/gui.py");

    candidates
        << QStringLiteral("C:/1PDF-Importer-LibreCAD/launch_lcpdf_gui.pyw")
        << QStringLiteral("C:/1PDF-Importer-LibreCAD/gui.py");

    candidates
        << QDir::cleanPath(appDir + "/../1PDF-Importer-LibreCAD/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(appDir + "/../1PDF-Importer-LibreCAD/gui.py");

    const QString home = QDir::homePath();
    candidates
        << QDir::cleanPath(home + "/LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(home + "/LibreCAD-PDF-Importer/gui.py")
        << QDir::cleanPath(home + "/Desktop/LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(home + "/Desktop/LibreCAD-PDF-Importer/gui.py");

    const QString localApp = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation);
    if (!localApp.isEmpty()) {
        candidates
            << QDir::cleanPath(localApp + "/BlueCollar/LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw")
            << QDir::cleanPath(localApp + "/BlueCollar/LibreCAD-PDF-Importer/gui.py");
    }

    return candidates;
}

QStringList candidatePortableExes() {
    QStringList candidates;

    const QString envExe = qEnvironmentVariable("BC_LC_IMPORTER_EXE").trimmed();
    if (!envExe.isEmpty()) {
        candidates << QDir::fromNativeSeparators(envExe);
    }

    const QString appDir = QCoreApplication::applicationDirPath();
    candidates
        << QDir::cleanPath(appDir + "/LibreCAD-PDF-Importer.exe")
        << QDir::cleanPath(appDir + "/lcpdf-gui.exe")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer.exe")
        << QDir::cleanPath(appDir + "/../lcpdf-gui.exe")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer/LibreCAD-PDF-Importer.exe")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer/lcpdf-gui.exe")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer-Portable/LibreCAD-PDF-Importer.exe")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer-Portable/lcpdf-gui.exe");

    const QString home = QDir::homePath();
    candidates
        << QDir::cleanPath(home + "/LibreCAD-PDF-Importer/LibreCAD-PDF-Importer.exe")
        << QDir::cleanPath(home + "/LibreCAD-PDF-Importer/lcpdf-gui.exe")
        << QDir::cleanPath(home + "/Desktop/LibreCAD-PDF-Importer/LibreCAD-PDF-Importer.exe")
        << QDir::cleanPath(home + "/Desktop/LibreCAD-PDF-Importer/lcpdf-gui.exe");

    const QString localAppData = qEnvironmentVariable("LOCALAPPDATA");
    if (!localAppData.isEmpty()) {
        const QString localPrograms =
            localAppData + "/Programs/BlueCollar Systems/LibreCAD PDF Importer";
        candidates
            << QDir::cleanPath(localPrograms + "/LibreCAD-PDF-Importer.exe")
            << QDir::cleanPath(localPrograms + "/lcpdf-gui.exe");
    }

    const QString programFiles = qEnvironmentVariable("ProgramFiles");
    if (!programFiles.isEmpty()) {
        const QString installDir = programFiles + "/BlueCollar Systems/LibreCAD PDF Importer";
        candidates
            << QDir::cleanPath(installDir + "/LibreCAD-PDF-Importer.exe")
            << QDir::cleanPath(installDir + "/lcpdf-gui.exe");
    }

    const QString programFilesX86 = qEnvironmentVariable("ProgramFiles(x86)");
    if (!programFilesX86.isEmpty()) {
        const QString installDir = programFilesX86 + "/BlueCollar Systems/LibreCAD PDF Importer";
        candidates
            << QDir::cleanPath(installDir + "/LibreCAD-PDF-Importer.exe")
            << QDir::cleanPath(installDir + "/lcpdf-gui.exe");
    }

    const QString roamingData = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation);
    if (!roamingData.isEmpty()) {
        const QString roamingPrograms =
            roamingData + "/Programs/BlueCollar Systems/LibreCAD PDF Importer";
        candidates
            << QDir::cleanPath(roamingPrograms + "/LibreCAD-PDF-Importer.exe")
            << QDir::cleanPath(roamingPrograms + "/lcpdf-gui.exe");
    }

    candidates
        << QStringLiteral("C:/1PDF-Importer-LibreCAD/dist/LibreCAD-PDF-Importer/LibreCAD-PDF-Importer.exe")
        << QStringLiteral("C:/1PDF-Importer-LibreCAD/dist/windows-portable/lcpdf-gui.exe");

    return candidates;
}

QString resolveScriptPath(const QSettings &settings) {
    const QString fromSettings =
        QDir::fromNativeSeparators(settings.value("script_path").toString().trimmed());
    if (!fromSettings.isEmpty() && QFileInfo::exists(fromSettings)) {
        return fromSettings;
    }

    for (const QString &candidate : candidateScripts()) {
        if (QFileInfo::exists(candidate)) {
            return candidate;
        }
    }

    for (const QString &candidate : candidatePortableExes()) {
        if (QFileInfo::exists(candidate)) {
            return candidate;
        }
    }

    return QString();
}

QString chooseScript(QWidget *parent, const QString &currentPath) {
    const QString startPath = currentPath.isEmpty()
                                  ? QStringLiteral("C:/1PDF-Importer-LibreCAD")
                                  : currentPath;
    return QFileDialog::getOpenFileName(
        parent,
        QObject::tr("Locate LC Importer Launcher"),
        startPath,
        QObject::tr("Importer Apps (*.exe *.py *.pyw);;All Files (*.*)")
    );
}

QString choosePythonExecutable(QWidget *parent, const QString &currentPath) {
    const QString startPath = currentPath.isEmpty()
                                  ? QStringLiteral("C:/Program Files/Python312")
                                  : currentPath;
    return QFileDialog::getOpenFileName(
        parent,
        QObject::tr("Optional: Choose Python Executable"),
        startPath,
        QObject::tr("Executables (*.exe);;All Files (*.*)")
    );
}

bool launchImporterProcess(const QString &scriptPath, const QString &pythonPath, QString *errorOut) {
    const QString normalizedScript = QDir::fromNativeSeparators(scriptPath);
    const QString scriptDir = QFileInfo(normalizedScript).absolutePath();

    if (normalizedScript.endsWith(".exe", Qt::CaseInsensitive)) {
        const bool ok = QProcess::startDetached(normalizedScript, QStringList(), scriptDir);
        if (ok) {
            if (errorOut) {
                errorOut->clear();
            }
            return true;
        }
        if (errorOut) {
            *errorOut = QObject::tr("Could not launch importer application: %1").arg(normalizedScript);
        }
        return false;
    }

    QStringList pythonCandidates;
    if (!pythonPath.trimmed().isEmpty()) {
        pythonCandidates << pythonPath.trimmed();
    }

    const QString envPython = qEnvironmentVariable("BC_LC_IMPORTER_PYTHON").trimmed();
    if (!envPython.isEmpty()) {
        pythonCandidates << envPython;
    }

    pythonCandidates << "pythonw.exe" << "pythonw" << "python.exe" << "python" << "py.exe" << "py";

    for (const QString &candidate : pythonCandidates) {
        QString program = candidate;
        if (!QFileInfo(candidate).exists()) {
            const QString resolved = QStandardPaths::findExecutable(candidate);
            if (!resolved.isEmpty()) {
                program = resolved;
            }
        }

        if (!QFileInfo(program).exists()) {
            continue;
        }

        QStringList args;
        if (QFileInfo(program).fileName().compare("py.exe", Qt::CaseInsensitive) == 0 ||
            QFileInfo(program).fileName().compare("py", Qt::CaseInsensitive) == 0) {
            args << "-3";
        }
        args << normalizedScript;

        const bool ok = QProcess::startDetached(program, args, scriptDir);
        if (ok) {
            if (errorOut) {
                errorOut->clear();
            }
            return true;
        }
    }

    const bool directLaunch = QProcess::startDetached(normalizedScript, QStringList(), scriptDir);
    if (directLaunch) {
        if (errorOut) {
            errorOut->clear();
        }
        return true;
    }

    if (errorOut) {
        *errorOut = QObject::tr("Could not launch importer script: %1").arg(normalizedScript);
    }
    return false;
}

void openSettingsDialog(QWidget *parent, QSettings &settings) {
    const QString currentScript = resolveScriptPath(settings);
    const QString selectedScript = chooseScript(parent, currentScript);
    if (selectedScript.isEmpty()) {
        return;
    }
    settings.setValue("script_path", QDir::fromNativeSeparators(selectedScript));

    const QString currentPython = settings.value("python_path").toString();
    const auto customPython = QMessageBox::question(
        parent,
        QObject::tr("Python Executable"),
        QObject::tr("Set a custom Python executable now?\n"
                    "Choose Yes to browse, or No to keep auto-detect.")
    );
    if (customPython == QMessageBox::Yes) {
        const QString selectedPython = choosePythonExecutable(parent, currentPython);
        if (!selectedPython.isEmpty()) {
            settings.setValue("python_path", QDir::fromNativeSeparators(selectedPython));
        }
    }
}

} // namespace

QString LC_BcLCPdfMenuPlugin::name() const {
    return tr("BlueCollar PDF Importer");
}

PluginCapabilities LC_BcLCPdfMenuPlugin::getCapabilities() const {
    PluginCapabilities caps;
    caps.menuEntryPoints
        << PluginMenuLocation("plugins_menu",
                              tr(kActionLaunch),
                              tr("Launch the BlueCollar PDF-to-DXF importer GUI"))
        << PluginMenuLocation("plugins_menu",
                              tr(kActionSettings),
                              tr("Configure importer script and Python executable paths"));
    return caps;
}

void LC_BcLCPdfMenuPlugin::execComm(Document_Interface *doc, QWidget *parent, QString cmd) {
    Q_UNUSED(doc);

    QSettings settings(QSettings::IniFormat, QSettings::UserScope, "LibreCAD", "bc_pdf_importer_plugin");

    const bool isSettingsAction = cmd.contains("Settings", Qt::CaseInsensitive);
    if (isSettingsAction) {
        openSettingsDialog(parent, settings);
        return;
    }

    QString scriptPath = resolveScriptPath(settings);
    if (scriptPath.isEmpty()) {
        QMessageBox::information(
            parent,
            tr("LC PDF Importer"),
            tr("Importer launcher was not found automatically.\n"
               "Please locate `LibreCAD-PDF-Importer.exe`, `lcpdf-gui.exe`, "
               "`launch_lcpdf_gui.pyw`, or `gui.py`.")
        );
        scriptPath = chooseScript(parent, QStringLiteral("C:/1PDF-Importer-LibreCAD"));
        if (scriptPath.isEmpty()) {
            return;
        }
        settings.setValue("script_path", QDir::fromNativeSeparators(scriptPath));
    }

    const QString pythonPath = settings.value("python_path").toString().trimmed();
    QString launchError;
    if (!launchImporterProcess(scriptPath, pythonPath, &launchError)) {
        QMessageBox::critical(
            parent,
            tr("LC PDF Importer"),
            tr("%1\n\nUse Plugins > %2 to set script/python paths.")
                .arg(launchError, tr(kActionSettings))
        );
    }
}
