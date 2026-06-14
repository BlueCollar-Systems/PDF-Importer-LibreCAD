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

    candidates
        << QStringLiteral("C:/1PDF-Importer-LibreCAD/launch_lcpdf_gui.pyw")
        << QStringLiteral("C:/1PDF-Importer-LibreCAD/gui.py");

    const QString appDir = QCoreApplication::applicationDirPath();
    candidates
        << QDir::cleanPath(appDir + "/../1PDF-Importer-LibreCAD/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(appDir + "/../1PDF-Importer-LibreCAD/gui.py");

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
        QObject::tr("Python Launchers (*.py *.pyw);;All Files (*.*)")
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
            tr("Importer launcher script was not found automatically.\n"
               "Please locate `launch_lcpdf_gui.pyw` or `gui.py`.")
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

