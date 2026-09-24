// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef BC_PLUGIN_SMOKE_H
#define BC_PLUGIN_SMOKE_H

#include <QString>
#include <QWidget>

// Stands in for QC_ApplicationWindow: exposes the same public slot the plugin
// uses to open the converted DXF.
class FakeLibreCadWindow : public QWidget {
    Q_OBJECT
public:
    QString openedPath;
public slots:
    void slotFileOpen(const QString &fileName) { openedPath = fileName; }
};

#endif
