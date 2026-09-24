// SPDX-License-Identifier: GPL-2.0-or-later
// BlueCollar PDF Importer menu plugin for LibreCAD 2.2.x (Qt 5).
//
// Plugins > Import PDF (BlueCollar)...
//   1. starts the BlueCollar importer GUI with --librecad-handoff <result.json>
//   2. the operator picks the PDF, text mode and options in that GUI and
//      presses Convert (the converter itself is unchanged)
//   3. after a successful conversion the GUI writes the DXF path to
//      <result.json> and closes
//   4. this plugin opens that DXF in the running LibreCAD (same code path as
//      File > Open), or inserts it as a block into the current drawing.
//
// The plugin never converts anything itself, so it cannot change the
// converter's accuracy. It only launches the GUI and loads its output.

#include "lcpdf_menu.h"

#include "../sdk/document_interface.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMessageBox>
#include <QMetaObject>
#include <QPointF>
#include <QProcess>
#include <QProgressDialog>
#include <QPushButton>
#include <QSettings>
#include <QStandardPaths>
#include <QStringList>
#include <QTextStream>
#include <QTimer>
#include <QWidget>

#ifdef Q_OS_WIN
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <signal.h>
#include <sys/types.h>
#endif

namespace {

const char *kActionOpen = "Import PDF (BlueCollar)...";
const char *kActionInsert = "Import PDF into Current Drawing (BlueCollar)...";
const char *kActionSettings = "PDF Importer Settings (BlueCollar)...";

// Written by the importer's "Install LibreCAD menu entry" action next to the
// plugin DLL. The name must NOT contain ".dll": LibreCAD tries to load every
// file in the plugins folder whose name contains ".dll".
const char *kSidecarName = "bc_lcpdf_menu-importer.txt";

const char *kHandoffFlag = "--librecad-handoff";

// Field diagnostics: set BC_LCPDF_PLUGIN_TRACE=1 before starting LibreCAD to
// append a step log to %TEMP%\bc_lcpdf_menu.log.
void trace(const QString &message) {
    static const bool enabled = !qEnvironmentVariable("BC_LCPDF_PLUGIN_TRACE").trimmed().isEmpty();
    if (!enabled) {
        return;
    }
    QFile log(QDir(QDir::tempPath()).filePath(QStringLiteral("bc_lcpdf_menu.log")));
    if (log.open(QIODevice::WriteOnly | QIODevice::Append)) {
        log.write((QDateTime::currentDateTime().toString(Qt::ISODateWithMs) + ' ' + message + '\n').toUtf8());
    }
}

// ---------------------------------------------------------------------------
// Locating the importer
// ---------------------------------------------------------------------------

QString pluginModuleDirectory() {
#ifdef Q_OS_WIN
    HMODULE module = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            reinterpret_cast<LPCWSTR>(&pluginModuleDirectory),
                            &module)) {
        return QString();
    }
    wchar_t buffer[32768];
    const DWORD length = GetModuleFileNameW(module, buffer, 32768);
    if (length == 0 || length >= 32768) {
        return QString();
    }
    return QFileInfo(QString::fromWCharArray(buffer, static_cast<int>(length))).absolutePath();
#else
    return QString();
#endif
}

QString userPluginDirectory() {
    const QString documents = QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
    if (documents.isEmpty()) {
        return QString();
    }
    return QDir::cleanPath(documents + "/LibreCAD/plugins");
}

QString readSidecarPath(const QString &directory) {
    if (directory.isEmpty()) {
        return QString();
    }
    QFile file(QDir(directory).filePath(QString::fromLatin1(kSidecarName)));
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return QString();
    }
    QTextStream stream(&file);
    stream.setCodec("UTF-8");
    while (!stream.atEnd()) {
        const QString line = stream.readLine().trimmed();
        if (!line.isEmpty() && !line.startsWith('#')) {
            return QDir::fromNativeSeparators(line);
        }
    }
    return QString();
}

QStringList candidateScripts() {
    QStringList candidates;

    const QString envScript = qEnvironmentVariable("BC_LC_IMPORTER_SCRIPT").trimmed();
    if (!envScript.isEmpty()) {
        candidates << QDir::fromNativeSeparators(envScript);
    }

    const QString appDir = QCoreApplication::applicationDirPath();
    candidates
        << QDir::cleanPath(appDir + "/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(appDir + "/gui.py")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(appDir + "/../LibreCAD-PDF-Importer/gui.py");

    const QString home = QDir::homePath();
    candidates
        << QDir::cleanPath(home + "/LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw")
        << QDir::cleanPath(home + "/Desktop/LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw");

    const QString localApp = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation);
    if (!localApp.isEmpty()) {
        candidates
            << QDir::cleanPath(localApp + "/BlueCollar/LibreCAD-PDF-Importer/launch_lcpdf_gui.pyw");
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
    const QStringList names = {QStringLiteral("lcpdf-gui.exe"),
                               QStringLiteral("LibreCAD-PDF-Importer.exe")};
    QStringList folders = {
        appDir,
        appDir + "/../LibreCAD-PDF-Importer",
        appDir + "/../LibreCAD-PDF-Importer-Portable",
        QDir::homePath() + "/LibreCAD-PDF-Importer",
        QDir::homePath() + "/Desktop/LibreCAD-PDF-Importer",
    };
    const QString localAppData = qEnvironmentVariable("LOCALAPPDATA");
    if (!localAppData.isEmpty()) {
        folders << localAppData + "/Programs/BlueCollar Systems/LibreCAD PDF Importer";
    }
    const QString programFiles = qEnvironmentVariable("ProgramFiles");
    if (!programFiles.isEmpty()) {
        folders << programFiles + "/BlueCollar Systems/LibreCAD PDF Importer";
    }
    for (const QString &folder : folders) {
        for (const QString &name : names) {
            candidates << QDir::cleanPath(folder + "/" + name);
        }
    }
    return candidates;
}

QString resolveLauncherPath(const QSettings &settings) {
    // An explicit environment override wins, then the path the operator pinned
    // in Settings, then the path the importer's installer recorded.
    const QString envExe = QDir::fromNativeSeparators(qEnvironmentVariable("BC_LC_IMPORTER_EXE").trimmed());
    if (!envExe.isEmpty() && QFileInfo::exists(envExe)) {
        return envExe;
    }
    const QString envScript = QDir::fromNativeSeparators(qEnvironmentVariable("BC_LC_IMPORTER_SCRIPT").trimmed());
    if (!envScript.isEmpty() && QFileInfo::exists(envScript)) {
        return envScript;
    }

    const QString pinned =
        QDir::fromNativeSeparators(settings.value("script_path").toString().trimmed());
    if (!pinned.isEmpty() && QFileInfo::exists(pinned)) {
        return pinned;
    }

    for (const QString &directory : {pluginModuleDirectory(), userPluginDirectory()}) {
        const QString recorded = readSidecarPath(directory);
        if (!recorded.isEmpty() && QFileInfo::exists(recorded)) {
            return recorded;
        }
    }

    for (const QString &candidate : candidatePortableExes()) {
        if (QFileInfo::exists(candidate)) {
            return candidate;
        }
    }
    for (const QString &candidate : candidateScripts()) {
        if (QFileInfo::exists(candidate)) {
            return candidate;
        }
    }
    return QString();
}

QString chooseLauncher(QWidget *parent, const QString &currentPath) {
    QString startPath = currentPath;
    if (startPath.isEmpty()) {
        startPath = QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
    }
    if (startPath.isEmpty()) {
        startPath = QDir::homePath();
    }
    return QFileDialog::getOpenFileName(
        parent,
        QObject::tr("Locate the BlueCollar PDF Importer (lcpdf-gui.exe)"),
        startPath,
        QObject::tr("Importer Apps (*.exe *.py *.pyw);;All Files (*.*)"));
}

QString choosePythonExecutable(QWidget *parent, const QString &currentPath) {
    const QString startPath = currentPath.isEmpty()
                                  ? QStringLiteral("C:/Program Files/Python312")
                                  : currentPath;
    return QFileDialog::getOpenFileName(
        parent,
        QObject::tr("Optional: Choose Python Executable"),
        startPath,
        QObject::tr("Executables (*.exe);;All Files (*.*)"));
}

// ---------------------------------------------------------------------------
// Launching the importer GUI in handoff mode
// ---------------------------------------------------------------------------

struct LaunchSpec {
    QString program;
    QStringList arguments;
};

bool isPythonScript(const QString &path) {
    return path.endsWith(".py", Qt::CaseInsensitive) || path.endsWith(".pyw", Qt::CaseInsensitive);
}

QString resolveProgram(const QString &candidate) {
    if (QFileInfo(candidate).isFile()) {
        return candidate;
    }
    return QStandardPaths::findExecutable(candidate);
}

bool buildLaunchSpec(const QString &launcher, const QString &pythonPath,
                     const QString &handoffPath, LaunchSpec *spec, QString *error) {
    const QStringList handoffArgs = {QString::fromLatin1(kHandoffFlag),
                                     QDir::toNativeSeparators(handoffPath)};
    if (!isPythonScript(launcher)) {
        spec->program = launcher;
        spec->arguments = handoffArgs;
        return true;
    }

    QStringList pythonCandidates;
    if (!pythonPath.trimmed().isEmpty()) {
        pythonCandidates << pythonPath.trimmed();
    }
    const QString envPython = qEnvironmentVariable("BC_LC_IMPORTER_PYTHON").trimmed();
    if (!envPython.isEmpty()) {
        pythonCandidates << envPython;
    }
    pythonCandidates << "pythonw.exe" << "pythonw" << "python.exe" << "python3" << "python"
                     << "py.exe" << "py";

    for (const QString &candidate : pythonCandidates) {
        const QString program = resolveProgram(candidate);
        if (program.isEmpty()) {
            continue;
        }
        QStringList args;
        const QString base = QFileInfo(program).fileName();
        if (base.compare("py.exe", Qt::CaseInsensitive) == 0 ||
            base.compare("py", Qt::CaseInsensitive) == 0) {
            args << "-3";
        }
        args << QDir::toNativeSeparators(launcher) << handoffArgs;
        spec->program = program;
        spec->arguments = args;
        return true;
    }
    *error = QObject::tr("No Python interpreter was found to run %1.").arg(launcher);
    return false;
}

class ProcessWatch {
public:
    explicit ProcessWatch(qint64 pid) : pid_(pid) {
#ifdef Q_OS_WIN
        handle_ = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                              static_cast<DWORD>(pid));
#endif
    }
    ~ProcessWatch() {
#ifdef Q_OS_WIN
        if (handle_ != nullptr) {
            CloseHandle(handle_);
        }
#endif
    }
    ProcessWatch(const ProcessWatch &) = delete;
    ProcessWatch &operator=(const ProcessWatch &) = delete;

    bool running() const {
#ifdef Q_OS_WIN
        if (handle_ == nullptr) {
            return false;
        }
        return WaitForSingleObject(handle_, 0) == WAIT_TIMEOUT;
#else
        return pid_ > 0 && ::kill(static_cast<pid_t>(pid_), 0) == 0;
#endif
    }

private:
    qint64 pid_ = 0;
#ifdef Q_OS_WIN
    HANDLE handle_ = nullptr;
#endif
};

enum class HandoffOutcome { Delivered, ClosedWithoutDrawing, ImporterExited, StoppedWaiting };

struct HandoffResult {
    HandoffOutcome outcome = HandoffOutcome::ImporterExited;
    QString dxfPath;
    int degradedTextItems = 0;
    QString reportPath;
};

bool readHandoffFile(const QString &path, HandoffResult *result) {
    QFile file(path);
    if (!file.exists() || !file.open(QIODevice::ReadOnly)) {
        return false;
    }
    const QJsonDocument json = QJsonDocument::fromJson(file.readAll());
    if (!json.isObject()) {
        return false;  // still being written; the importer replaces it atomically
    }
    const QJsonObject object = json.object();
    const QString status = object.value("status").toString();
    if (status == "ok") {
        result->outcome = HandoffOutcome::Delivered;
        result->dxfPath = QDir::fromNativeSeparators(object.value("output_path").toString());
        result->degradedTextItems = object.value("degraded_text_items").toInt();
        result->reportPath = object.value("report_path").toString();
        return true;
    }
    if (status == "closed") {
        result->outcome = HandoffOutcome::ClosedWithoutDrawing;
        return true;
    }
    return false;
}

HandoffResult waitForHandoff(QWidget *parent, const QString &handoffPath, qint64 pid) {
    HandoffResult result;
    ProcessWatch watch(pid);

    QProgressDialog progress(parent);
    progress.setWindowTitle(QObject::tr("BlueCollar PDF Importer"));
    progress.setLabelText(QObject::tr(
        "The BlueCollar PDF Importer window is open.\n\n"
        "Choose the PDF, text mode and options there, then press Convert.\n"
        "When the conversion finishes, the DXF opens here in LibreCAD."));
    progress.setCancelButtonText(QObject::tr("Stop Waiting"));
    progress.setRange(0, 0);
    progress.setMinimumDuration(0);
    progress.setWindowModality(Qt::WindowModal);
    progress.setAutoClose(false);
    progress.setAutoReset(false);
    progress.show();

    QEventLoop loop;
    QTimer timer;
    int exitedTicks = 0;
    bool stopped = false;
    QObject::connect(&progress, &QProgressDialog::canceled, &loop, [&]() {
        stopped = true;
        loop.quit();
    });
    QObject::connect(&timer, &QTimer::timeout, &loop, [&]() {
        if (readHandoffFile(handoffPath, &result)) {
            loop.quit();
            return;
        }
        if (!watch.running()) {
            // Allow a moment for a final atomic rename to land.
            if (++exitedTicks >= 4) {
                result.outcome = HandoffOutcome::ImporterExited;
                loop.quit();
            }
        }
    });
    timer.start(250);
    loop.exec();
    timer.stop();
    // Closing a QProgressDialog emits canceled(); that is not the operator
    // pressing Stop Waiting, so disconnect before closing it.
    QObject::disconnect(&progress, nullptr, &loop, nullptr);
    progress.close();
    trace(QStringLiteral("wait loop finished stopped=%1").arg(stopped));

    if (stopped && result.outcome != HandoffOutcome::Delivered) {
        result.outcome = HandoffOutcome::StoppedWaiting;
    }
    return result;
}

bool openInLibreCad(QWidget *parent, const QString &dxfPath) {
    // QC_ApplicationWindow::slotFileOpen(const QString&) is a public slot and
    // is exactly what File > Open / drag-and-drop use. Queue it so it runs
    // after this plugin call (and LibreCAD's undo section) has finished.
    const QString nativePath = QDir::toNativeSeparators(dxfPath);
    for (QObject *target = parent; target != nullptr; target = target->parent()) {
        if (target->metaObject()->indexOfSlot("slotFileOpen(QString)") >= 0) {
            return QMetaObject::invokeMethod(target, "slotFileOpen", Qt::QueuedConnection,
                                             Q_ARG(QString, nativePath));
        }
    }
    return false;
}

bool insertIntoDrawing(Document_Interface *doc, const QString &dxfPath, QString *blockName) {
    if (doc == nullptr) {
        return false;
    }
    const QString name = doc->addBlockfromFromdisk(QDir::toNativeSeparators(dxfPath));
    if (name.isEmpty()) {
        return false;
    }
    doc->addInsert(name, QPointF(0.0, 0.0), QPointF(1.0, 1.0), 0.0);
    doc->updateView();
    *blockName = name;
    return true;
}

void openSettingsDialog(QWidget *parent, QSettings &settings) {
    const QString current = resolveLauncherPath(settings);
    QMessageBox box(parent);
    box.setWindowTitle(QObject::tr("BlueCollar PDF Importer Settings"));
    box.setText(current.isEmpty()
                    ? QObject::tr("The importer was not found automatically.")
                    : QObject::tr("Importer in use:\n%1").arg(QDir::toNativeSeparators(current)));
    box.setInformativeText(QObject::tr(
        "Normally the importer's \"Install LibreCAD menu entry\" button sets this up.\n"
        "Choose Browse to pin a different lcpdf-gui.exe (or launch_lcpdf_gui.pyw)."));
    QPushButton *browse = box.addButton(QObject::tr("Browse..."), QMessageBox::ActionRole);
    QPushButton *reset = box.addButton(QObject::tr("Use Installed / Auto-detect"), QMessageBox::ResetRole);
    box.addButton(QMessageBox::Close);
    box.exec();

    if (box.clickedButton() == reset) {
        settings.remove("script_path");
        settings.remove("python_path");
        return;
    }
    if (box.clickedButton() != browse) {
        return;
    }
    const QString selected = chooseLauncher(parent, current);
    if (selected.isEmpty()) {
        return;
    }
    settings.setValue("script_path", QDir::fromNativeSeparators(selected));
    if (isPythonScript(selected)) {
        const auto customPython = QMessageBox::question(
            parent, QObject::tr("Python Executable"),
            QObject::tr("Set a custom Python executable now?\n"
                        "Choose Yes to browse, or No to keep auto-detect."));
        if (customPython == QMessageBox::Yes) {
            const QString python = choosePythonExecutable(parent, settings.value("python_path").toString());
            if (!python.isEmpty()) {
                settings.setValue("python_path", QDir::fromNativeSeparators(python));
            }
        }
    }
}

QString newHandoffPath() {
    const QString stamp = QString::number(QDateTime::currentMSecsSinceEpoch());
    const QString pid = QString::number(QCoreApplication::applicationPid());
    return QDir(QDir::tempPath()).filePath(
        QStringLiteral("bc_lcpdf_handoff_%1_%2.json").arg(pid, stamp));
}

}  // namespace

QString LC_BcLCPdfMenuPlugin::name() const {
    return tr("BlueCollar PDF Importer");
}

PluginCapabilities LC_BcLCPdfMenuPlugin::getCapabilities() const {
    PluginCapabilities caps;
    caps.menuEntryPoints
        << PluginMenuLocation(QStringLiteral("plugins_menu"), tr(kActionOpen))
        << PluginMenuLocation(QStringLiteral("plugins_menu"), tr(kActionInsert))
        << PluginMenuLocation(QStringLiteral("plugins_menu"), tr(kActionSettings));
    return caps;
}

void LC_BcLCPdfMenuPlugin::execComm(Document_Interface *doc, QWidget *parent, QString cmd) {
    QSettings settings(QSettings::IniFormat, QSettings::UserScope, "LibreCAD",
                       "bc_pdf_importer_plugin");

    if (cmd == tr(kActionSettings) || cmd.contains("Settings", Qt::CaseInsensitive)) {
        openSettingsDialog(parent, settings);
        return;
    }
    const bool insertMode = (cmd == tr(kActionInsert)) || cmd.contains("Current Drawing");

    QString launcher = resolveLauncherPath(settings);
    if (launcher.isEmpty()) {
        QMessageBox::information(
            parent, tr("BlueCollar PDF Importer"),
            tr("The importer was not found automatically.\n\n"
               "Open lcpdf-gui.exe from the Windows portable ZIP and press "
               "\"Install LibreCAD menu entry\" once, or locate "
               "lcpdf-gui.exe / LibreCAD-PDF-Importer.exe / launch_lcpdf_gui.pyw now."));
        launcher = chooseLauncher(parent, QString());
        if (launcher.isEmpty()) {
            return;
        }
        settings.setValue("script_path", QDir::fromNativeSeparators(launcher));
    }

    const QString handoffPath = newHandoffPath();
    QFile::remove(handoffPath);

    LaunchSpec spec;
    QString error;
    if (!buildLaunchSpec(launcher, settings.value("python_path").toString(), handoffPath, &spec,
                         &error)) {
        QMessageBox::critical(parent, tr("BlueCollar PDF Importer"),
                              tr("%1\n\nUse Plugins > %2 to set the paths.")
                                  .arg(error, tr(kActionSettings)));
        return;
    }

    qint64 pid = 0;
    const QString workDir = QFileInfo(launcher).absolutePath();
    if (!QProcess::startDetached(spec.program, spec.arguments, workDir, &pid)) {
        QMessageBox::critical(parent, tr("BlueCollar PDF Importer"),
                              tr("Could not start the importer:\n%1\n\nUse Plugins > %2 to set the paths.")
                                  .arg(QDir::toNativeSeparators(spec.program), tr(kActionSettings)));
        return;
    }

    trace(QStringLiteral("started %1 pid=%2 handoff=%3").arg(spec.program).arg(pid).arg(handoffPath));
    const HandoffResult result = waitForHandoff(parent, handoffPath, pid);
    QFile::remove(handoffPath);
    trace(QStringLiteral("handoff outcome=%1 dxf=%2")
              .arg(static_cast<int>(result.outcome))
              .arg(result.dxfPath));

    switch (result.outcome) {
    case HandoffOutcome::ClosedWithoutDrawing:
    case HandoffOutcome::StoppedWaiting:
        return;
    case HandoffOutcome::ImporterExited:
        QMessageBox::information(
            parent, tr("BlueCollar PDF Importer"),
            tr("The importer closed without handing a drawing back to LibreCAD.\n\n"
               "If you did convert a PDF, open the DXF with File > Open. "
               "Importer versions older than 1.0.104 cannot hand drawings back; "
               "update the importer to get automatic opening."));
        return;
    case HandoffOutcome::Delivered:
        break;
    }

    if (result.dxfPath.isEmpty() || !QFileInfo::exists(result.dxfPath)) {
        trace(QStringLiteral("reported DXF missing"));
        QMessageBox::warning(parent, tr("BlueCollar PDF Importer"),
                             tr("The importer reported a DXF that does not exist:\n%1")
                                 .arg(QDir::toNativeSeparators(result.dxfPath)));
        return;
    }

    if (insertMode) {
        QString blockName;
        if (!insertIntoDrawing(doc, result.dxfPath, &blockName)) {
            QMessageBox::warning(parent, tr("BlueCollar PDF Importer"),
                                 tr("LibreCAD could not insert the DXF into this drawing.\n"
                                    "Open it with File > Open instead:\n%1")
                                     .arg(QDir::toNativeSeparators(result.dxfPath)));
        }
        return;
    }

    trace(QStringLiteral("opening via slotFileOpen: %1").arg(result.dxfPath));
    if (!openInLibreCad(parent, result.dxfPath)) {
        QMessageBox::information(parent, tr("BlueCollar PDF Importer"),
                                 tr("Conversion finished. Open the DXF with File > Open:\n%1")
                                     .arg(QDir::toNativeSeparators(result.dxfPath)));
    }
}
