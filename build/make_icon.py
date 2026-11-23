"""Gera app/ui/abonario.ico e abonario.png (ícone do programa) com o próprio Qt."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

OUT = Path(__file__).resolve().parent.parent / "app" / "ui"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.18, size * 0.18)
    p.fillPath(path, QColor("#8a3b12"))
    p.setPen(QColor("#fbf3e4"))
    f = QFont("Georgia")
    f.setBold(True)
    f.setPixelSize(int(size * 0.66))
    p.setFont(f)
    p.drawText(r.adjusted(0, -size * 0.04, 0, 0), Qt.AlignCenter, "A")
    p.setPen(QColor("#f2c879"))
    f2 = QFont("Georgia")
    f2.setPixelSize(int(size * 0.2))
    p.setFont(f2)
    p.drawText(r.adjusted(size * 0.52, size * 0.52, 0, 0), Qt.AlignCenter, "“”")
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication([])
    draw(256).save(str(OUT / "abonario.png"))
    draw(256).save(str(OUT / "abonario.ico"))
    print("ícone gerado em", OUT)
