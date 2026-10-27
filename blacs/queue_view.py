#####################################################################
#                                                                   #
# /queue_view.py                                                    #
#                                                                   #
# Copyright 2026, Monash University and contributors                #
#                                                                   #
# This file is part of the program BLACS, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
"""The list of files in the queue, and a widget that displays it."""

import logging
import os

from qtutils.qt.QtCore import Qt, QAbstractListModel, QModelIndex
from qtutils.qt.QtWidgets import QAbstractItemView, QHeaderView, QTableView

# Looking up an enum member is slow under PySide6, and data() is called for each role
# of each visible row on every repaint:
DISPLAY_ROLE = Qt.DisplayRole
TOOLTIP_ROLE = Qt.ToolTipRole


class QueueModel(QAbstractListModel):
    """The paths of the files in the queue, and the DeviceOrders of each file or None.
    Rows show the file name, with the full path as a tooltip. Must be used only from
    the main thread."""

    def __init__(self):
        QAbstractListModel.__init__(self)
        self._entries = []

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._entries)

    def data(self, index, role=DISPLAY_ROLE):
        if role == DISPLAY_ROLE:
            return os.path.basename(self._entries[index.row()][0])
        if role == TOOLTIP_ROLE:
            return self._entries[index.row()][0]
        return None

    def file_count(self):
        return len(self._entries)

    def paths(self):
        return [path for path, _ in self._entries]

    def insert(self, position, entries):
        """Insert a list of (path, device_orders) tuples at a position in the queue"""
        if not entries:
            return
        self.beginInsertRows(QModelIndex(), position, position + len(entries) - 1)
        self._entries[position:position] = entries
        self.endInsertRows()

    def append(self, entries):
        self.insert(len(self._entries), entries)

    def pop(self, position):
        """Remove a file from the queue and return its (path, device_orders) tuple"""
        self.beginRemoveRows(QModelIndex(), position, position)
        entry = self._entries.pop(position)
        self.endRemoveRows()
        return entry

    def move(self, source, destination):
        """Move the file at position source to position destination"""
        if source == destination:
            return
        # beginMoveRows() takes the position before the move at which to insert the row:
        child = destination + 1 if destination > source else destination
        self.beginMoveRows(QModelIndex(), source, source, QModelIndex(), child)
        self._entries.insert(destination, self._entries.pop(source))
        self.endMoveRows()

    def clear(self):
        self.beginResetModel()
        self._entries = []
        self.endResetModel()


class QueueView(QTableView):
    """A view of a QueueModel. Files dropped onto the view are passed to add_to_queue(),
    and the Delete key calls delete_selection()."""

    def __init__(self, *args, **kwargs):
        QTableView.__init__(self, *args, **kwargs)
        self.add_to_queue = None
        self.delete_selection = None
        self._logger = logging.getLogger('BLACS.QueueManager')
        self.horizontalHeader().hide()
        self.horizontalHeader().setStretchLastSection(True)
        vertical_header = self.verticalHeader()
        vertical_header.hide()
        vertical_header.setSectionResizeMode(QHeaderView.Fixed)
        vertical_header.setDefaultSectionSize(self.fontMetrics().height() + 4)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setAutoScroll(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setAcceptDrops(True)

    def selected_positions(self):
        """Return the sorted positions of the selected files in the queue"""
        return sorted(index.row() for index in self.selectionModel().selectedRows())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            event.accept()
            if self.delete_selection:
                self.delete_selection()
            return
        QTableView.keyPressEvent(self, event)

    def moveCursor(self, cursor_action, modifiers):
        # Home and End go to the first and last row, as ctrl-Home and ctrl-End do in a
        # QTableView:
        if cursor_action in (QAbstractItemView.MoveHome, QAbstractItemView.MoveEnd):
            modifiers |= Qt.ControlModifier
        return QTableView.moveCursor(self, cursor_action, modifiers)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()

            for url in event.mimeData().urls():
                path = str(url.toLocalFile())
                if path.endswith('.h5') or path.endswith('.hdf5'):
                    self._logger.info('Acceptable file dropped. Path is %s', path)
                    if self.add_to_queue:
                        self.add_to_queue(str(path))
                    else:
                        self._logger.info('Dropped file not added to queue because there is no access to the neccessary add_to_queue method')
                else:
                    self._logger.info('Invalid file dropped. Path was %s', path)
        else:
            event.ignore()
