// SPDX-License-Identifier: GPL-2.0-or-later
// BlueCollar PDF Importer menu plugin for LibreCAD 2.2.x (Qt 5).
#ifndef BC_LCPDF_MENU_H
#define BC_LCPDF_MENU_H

#include <QObject>

#include "../sdk/qc_plugininterface.h"

class LC_BcLCPdfMenuPlugin : public QObject, QC_PluginInterface {
    Q_OBJECT
    Q_INTERFACES(QC_PluginInterface)
    Q_PLUGIN_METADATA(IID LC_DocumentInterface_iid FILE "lcpdf_menu.json")

public:
    QString name() const override;
    PluginCapabilities getCapabilities() const override;
    void execComm(Document_Interface *doc, QWidget *parent, QString cmd) override;
};

#endif
