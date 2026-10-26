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
"""The list of files in the queue, and a widget that displays it. The widget draws only
the rows that are visible, so that adding and removing files takes the same time for any
length of queue."""

import logging
import os

from qtutils.qt.QtCore import Qt, QObject, QRect, QEvent, Signal
from qtutils.qt.QtGui import QKeySequence, QPainter, QPalette
from qtutils.qt.QtWidgets import (
    QAbstractScrollArea,
    QStyle,
    QStyleOptionFocusRect,
    QToolTip,
)


class QueueModel(QObject):
    """The paths of the files in the queue, and the DeviceOrders of each file or None.
    Must be used only from the main thread."""

    # Emitted after each change, with the position of the first file that may have
    # changed and a list of the paths of any files that were removed:
    changed = Signal(int, list)

    def __init__(self):
        QObject.__init__(self)
        self._entries = []

    def file_count(self):
        return len(self._entries)

    def path(self, position):
        return self._entries[position][0]

    def paths(self):
        return [path for path, _ in self._entries]

    def positions(self, paths):
        """Return the sorted positions of the given paths in the queue"""
        return [i for i, (path, _) in enumerate(self._entries) if path in paths]

    def insert(self, position, entries):
        """Insert a list of (path, device_orders) tuples at a position in the queue"""
        self._entries[position:position] = entries
        self.changed.emit(position, [])

    def append(self, entries):
        self.insert(len(self._entries), entries)

    def pop(self, position):
        """Remove a file from the queue and return its (path, device_orders) tuple"""
        entry = self._entries.pop(position)
        self.changed.emit(position, [entry[0]])
        return entry

    def move(self, source, destination):
        """Move the file at position source to position destination"""
        if source != destination:
            self._entries.insert(destination, self._entries.pop(source))
            self.changed.emit(min(source, destination), [])

    def clear(self):
        removed = self.paths()
        self._entries = []
        self.changed.emit(0, removed)


class QueueView(QAbstractScrollArea):
    """A list of the file names in a QueueModel, with the full path as a tooltip. Rows
    are selected with the mouse and keyboard as in a QListView with extended selection.
    Files dropped onto the view are passed to add_to_queue(), and the Delete key calls
    delete_selection()."""

    MARGIN = 3

    def __init__(self, *args, **kwargs):
        QAbstractScrollArea.__init__(self, *args, **kwargs)
        self.add_to_queue = None
        self.delete_selection = None
        self._logger = logging.getLogger('BLACS.QueueManager')
        self._model = QueueModel()
        self._model.changed.connect(self._on_model_changed)
        # Paths of the selected files, of the file with the keyboard focus, and of the
        # file at which a shift-click selection starts:
        self._selected = set()
        self._current = None
        self._anchor = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setAcceptDrops(True)
        self.verticalScrollBar().setSingleStep(1)

    def setModel(self, model):
        self._model.changed.disconnect(self._on_model_changed)
        self._model = model
        model.changed.connect(self._on_model_changed)
        self._selected = set()
        self._current = self._anchor = None
        self._update_scrollbar()
        self.viewport().update()

    def selected_positions(self):
        """Return the sorted positions of the selected files in the queue"""
        return self._model.positions(self._selected)

    def select(self, positions):
        """Select the files at the given positions, and only those"""
        self._selected = {self._model.path(i) for i in positions}
        if positions:
            self._current = self._anchor = self._model.path(positions[-1])
        self.viewport().update()

    def _row_height(self):
        return self.fontMetrics().height()

    def _visible_rows(self):
        """Return the number of rows that fit entirely in the viewport"""
        return max(1, self.viewport().height() // self._row_height())

    def _first_row(self):
        return self.verticalScrollBar().value()

    def _row_at(self, y):
        """Return the position of the file at a y coordinate in the viewport, or None"""
        row = self._first_row() + y // self._row_height()
        if 0 <= row < self._model.file_count():
            return row
        return None

    def _update_scrollbar(self):
        visible = self._visible_rows()
        scrollbar = self.verticalScrollBar()
        scrollbar.setPageStep(visible)
        scrollbar.setRange(0, max(0, self._model.file_count() - visible))

    def _on_model_changed(self, first_changed, removed):
        self._selected.difference_update(removed)
        if self._current in removed:
            self._current = None
        if self._anchor in removed:
            self._anchor = None
        self._update_scrollbar()
        if first_changed <= self._first_row() + self._visible_rows():
            self.viewport().update()

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()

    def resizeEvent(self, event):
        QAbstractScrollArea.resizeEvent(self, event)
        self._update_scrollbar()

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        height = self._row_height()
        width = self.viewport().width()
        first = self._first_row()
        rect = event.rect()
        start = first + rect.top() // height
        stop = min(self._model.file_count(), first + rect.bottom() // height + 1)
        palette = self.palette()
        group = QPalette.Active if self.isActiveWindow() else QPalette.Inactive
        metrics = self.fontMetrics()
        text_width = width - 2 * self.MARGIN
        for row in range(start, stop):
            path = self._model.path(row)
            row_rect = QRect(0, (row - first) * height, width, height)
            if path in self._selected:
                painter.fillRect(row_rect, palette.brush(group, QPalette.Highlight))
                painter.setPen(palette.color(group, QPalette.HighlightedText))
            else:
                painter.setPen(palette.color(group, QPalette.Text))
            name = metrics.elidedText(os.path.basename(path), Qt.ElideRight, text_width)
            painter.drawText(row_rect.adjusted(self.MARGIN, 0, -self.MARGIN, 0),
                             Qt.AlignLeft | Qt.AlignVCenter, name)
            if path == self._current and self.hasFocus():
                option = QStyleOptionFocusRect()
                option.initFrom(self)
                option.rect = row_rect
                option.backgroundColor = palette.color(group, QPalette.Base)
                self.style().drawPrimitive(QStyle.PE_FrameFocusRect, option, painter, self)

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip:
            row = self._row_at(event.pos().y())
            if row is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), self._model.path(row), self.viewport())
            return True
        return QAbstractScrollArea.viewportEvent(self, event)

    def _select_to(self, row, extend):
        """Make row the current row and select from the anchor to it. If extend is
        False, the previous selection is cleared first."""
        path = self._model.path(row)
        if self._anchor is None:
            self._anchor = path
        anchor_rows = self._model.positions({self._anchor})
        anchor = anchor_rows[0] if anchor_rows else row
        selection = {self._model.path(i) for i in range(min(anchor, row), max(anchor, row) + 1)}
        self._selected = self._selected | selection if extend else selection
        self._current = path

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        row = self._row_at(event.pos().y())
        modifiers = event.modifiers()
        if row is None:
            if not modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
                self._selected = set()
        elif modifiers & Qt.ShiftModifier:
            self._select_to(row, extend=bool(modifiers & Qt.ControlModifier))
        else:
            path = self._model.path(row)
            if modifiers & Qt.ControlModifier:
                self._selected ^= {path}
            else:
                self._selected = {path}
            self._current = self._anchor = path
        self.viewport().update()

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.LeftButton or self._anchor is None:
            return
        row = self._row_at(min(max(event.pos().y(), 0), self.viewport().height() - 1))
        if row is not None:
            self._select_to(row, extend=bool(event.modifiers() & Qt.ControlModifier))
            self._scroll_to(row)
            self.viewport().update()

    def _scroll_to(self, row):
        scrollbar = self.verticalScrollBar()
        if row < scrollbar.value():
            scrollbar.setValue(row)
        elif row >= scrollbar.value() + self._visible_rows():
            scrollbar.setValue(row - self._visible_rows() + 1)

    def keyPressEvent(self, event):
        key = event.key()
        count = self._model.file_count()
        if key == Qt.Key_Delete:
            if self.delete_selection:
                self.delete_selection()
            return
        if event.matches(QKeySequence.SelectAll):
            self._selected = set(self._model.paths())
            self.viewport().update()
            return
        current_rows = self._model.positions({self._current}) if self._current else []
        current = current_rows[0] if current_rows else -1
        page = self._visible_rows()
        targets = {
            Qt.Key_Up: current - 1,
            Qt.Key_Down: current + 1,
            Qt.Key_PageUp: current - page,
            Qt.Key_PageDown: current + page,
            Qt.Key_Home: 0,
            Qt.Key_End: count - 1,
        }
        if key not in targets or not count:
            QAbstractScrollArea.keyPressEvent(self, event)
            return
        row = min(max(targets[key], 0), count - 1)
        if event.modifiers() & Qt.ShiftModifier:
            self._select_to(row, extend=False)
        else:
            path = self._model.path(row)
            self._selected = {path}
            self._current = self._anchor = path
        self._scroll_to(row)
        self.viewport().update()

    def focusInEvent(self, event):
        QAbstractScrollArea.focusInEvent(self, event)
        self.viewport().update()

    def focusOutEvent(self, event):
        QAbstractScrollArea.focusOutEvent(self, event)
        self.viewport().update()

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
