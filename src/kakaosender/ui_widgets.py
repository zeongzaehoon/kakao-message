"""Explicitly painted controls keep selection legible under either OS theme."""
from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QMouseEvent, QPaintEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QSpinBox, QStyle, QStyledItemDelegate, QStyleOptionButton,
    QStyleOptionSpinBox, QStyleOptionViewItem, QTableWidget, QWidget,
)


def paint_check(painter: QPainter, rect: QRect, checked: bool, enabled: bool) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = QRectF(rect.center().x() - 10, rect.center().y() - 10, 20, 20)
    painter.setPen(QPen(QColor("#777777" if enabled else "#444444"), 1.4))
    painter.setBrush(QColor("#fee500" if checked else "#292929" if enabled else "#252525"))
    if checked:
        painter.setPen(QPen(QColor("#dac500"), 1))
    painter.drawRoundedRect(box, 6, 6)
    painter.setPen(QPen(QColor("#191919" if enabled else "#666666"), 2,
                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    x, y = box.left(), box.top()
    if checked:
        painter.drawLine(QPoint(int(x + 5), int(y + 10)), QPoint(int(x + 9), int(y + 14)))
        painter.drawLine(QPoint(int(x + 9), int(y + 14)), QPoint(int(x + 16), int(y + 6)))
    elif not enabled:
        painter.drawLine(QPoint(int(x + 6), int(y + 10)), QPoint(int(x + 14), int(y + 10)))
    painter.restore()


class VisibleCheckBox(QCheckBox):
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        paint_check(painter, rect, self.isChecked(), self.isEnabled())

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)


class VisibleComboBox(QComboBox):
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#a0a0a0"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 16, self.height() // 2
        painter.drawLine(x - 3, y - 2, x, y + 1)
        painter.drawLine(x, y + 1, x + 3, y - 2)


class VisibleSpinBox(QSpinBox):
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#a0a0a0"), 1.2))
        for control, up in [(QStyle.SubControl.SC_SpinBoxUp, True), (QStyle.SubControl.SC_SpinBoxDown, False)]:
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, control, self)
            x, y = rect.center().x(), rect.center().y()
            painter.drawLine(x - 3, y, x + 3, y)
            if up:
                painter.drawLine(x, y - 3, x, y + 3)


class FriendDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        table = self.parent()
        check = index.siblingAtColumn(0)
        checked = check.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
        selectable = bool(check.flags() & Qt.ItemFlag.ItemIsEnabled)
        enabled = selectable and table.isEnabled()
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = ("#33322a" if checked else "#292929"
                      if option.state & QStyle.StateFlag.State_MouseOver else "#222222")
        painter.fillRect(rect, QColor(background))
        if index.column() == 0:
            paint_check(painter, rect, checked, enabled)
        elif index.column() == 1:
            name = str(index.data() or "")
            avatar = QRectF(rect.left() + 4, rect.center().y() - 23, 46, 46)
            colors = ["#3c4145", "#47423e", "#414544", "#424049"]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors[index.row() % len(colors)]))
            painter.drawRoundedRect(avatar, 18, 18)
            font = option.font
            font.setPixelSize(16)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#d3d3d3"))
            painter.drawText(avatar, Qt.AlignmentFlag.AlignCenter, name[:1])
            text_top = rect.top() + 17 if checked or not selectable else rect.center().y() - 11
            text_rect = QRect(rect.left() + 64, text_top, rect.width() - 72, 22)
            font.setPixelSize(15)
            painter.setFont(font)
            painter.setPen(QColor("#eeeeee" if enabled else "#777777"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, text_rect.width()))
            font.setBold(False)
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(QColor("#bca77e" if not selectable else "#8f8f8f"))
            note = "선택됨" if checked else "" if selectable else str(index.siblingAtColumn(2).data() or "선택 불가")
            painter.drawText(text_rect.translated(0, 22), Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(note, Qt.TextElideMode.ElideRight, text_rect.width()))
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor("#9b8c00"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 4, 4)
        painter.restore()

    def editorEvent(self, event: QEvent, model: QAbstractItemModel,
                    option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        # FriendTable owns toggles, avoiding a second toggle from Qt's delegate.
        return False


class FriendTable(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 3, parent)
        self.setItemDelegate(FriendDelegate(self))
        self.setMouseTracking(True)
        self.setShowGrid(False)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(80)
        self.setColumnHidden(2, True)
        self.setColumnWidth(0, 36)
        self.horizontalHeader().moveSection(0, 2)
        self.setAccessibleName("채팅방 선택 목록")
        self.setAccessibleDescription("대화방 행을 클릭하거나 방향키로 이동 후 스페이스 키로 선택합니다.")
        self._pressed_row = -1

    def toggle_row(self, row: int) -> None:
        item = self.item(row, 0)
        if self.isEnabled() and item and item.flags() & Qt.ItemFlag.ItemIsEnabled:
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)
            self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pressed_row = self.indexAt(event.position().toPoint()).row()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        row = self.indexAt(event.position().toPoint()).row()
        if event.button() == Qt.MouseButton.LeftButton and row == self._pressed_row and row >= 0:
            self.toggle_row(row)
        self._pressed_row = -1
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            self.toggle_row(self.currentRow())
            event.accept()
            return
        super().keyPressEvent(event)


def navigation_icon(kind: str) -> QIcon:
    icon = QIcon()
    for state, color in ((QIcon.State.Off, "#989898"), (QIcon.State.On, "#eeeeee")):
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        painter.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if kind == "friends":
            path = QPainterPath()
            path.moveTo(5, 17)
            path.cubicTo(1, 15, 1, 6, 6, 4)
            path.cubicTo(15, 0, 23, 6, 21, 13)
            path.cubicTo(20, 18, 15, 20, 10, 18)
            path.lineTo(5, 21)
            path.closeSubpath()
            painter.setBrush(QColor(color) if state == QIcon.State.On else Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        else:
            painter.drawEllipse(QRectF(5, 5, 14, 14))
            painter.drawEllipse(QRectF(9, 9, 6, 6))
            for x1, y1, x2, y2 in ((12,2,12,5),(12,19,12,22),(2,12,5,12),(19,12,22,12),
                                    (5,5,7,7),(17,17,19,19),(5,19,7,17),(17,7,19,5)):
                painter.drawLine(x1,y1,x2,y2)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
        icon.addPixmap(pixmap, QIcon.Mode.Active, state)
    return icon
