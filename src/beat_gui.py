"""PySide6 beat practice player for the audio-beat project."""

from __future__ import annotations

import json
import math
import struct
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import override

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class Song:
    audio: Path
    beats: tuple[float, ...]
    downbeats: frozenset[float]


def load_songs(root: Path) -> list[Song]:
    songs: list[Song] = []
    for audio in sorted(root.glob("*")):
        supported = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
        if not audio.is_file() or audio.suffix.lower() not in supported:
            continue
        beat_file = root.parent / "beats" / f"{audio.stem}.json"
        if not beat_file.exists():
            continue
        try:
            payload = json.loads(beat_file.read_text(encoding="utf-8"))
            beats = tuple(float(value) for value in payload.get("beats", []))
            downbeats = frozenset(float(value) for value in payload.get("downbeats", []))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        songs.append(Song(audio, beats, downbeats))
    return songs


def make_click() -> str:
    """Create a tiny click sound in the permitted runtime temp directory."""
    path = Path(tempfile.gettempdir()) / "audio_beat_click.wav"
    if path.exists():
        return str(path)
    rate, duration = 44100, 0.055
    frames = bytearray()
    for index in range(round(rate * duration)):
        t = index / rate
        envelope = max(0.0, 1.0 - t / duration)
        sample = int(0.45 * envelope * math.sin(2 * math.pi * 1450 * t) * 32767)
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(frames)
    return str(path)


class BeatTimeline(QWidget):
    """Paint a compact timeline with downbeats emphasized."""

    def __init__(self) -> None:
        super().__init__()
        self.beats: tuple[float, ...] = ()
        self.downbeats: frozenset[float] = frozenset()
        self.position = 0.0
        self.duration = 1.0
        self.setMinimumHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, song: Song | None, duration: float = 1.0) -> None:
        self.beats = song.beats if song else ()
        self.downbeats = song.downbeats if song else frozenset()
        self.duration = max(duration, self.beats[-1] if self.beats else 1.0)
        self.position = 0.0
        self.update()

    def set_position(self, seconds: float) -> None:
        self.position = seconds
        self.update()

    @override
    def paintEvent(self, event: object) -> None:
        del event
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor("#111820"))
            left, right = 28.0, self.width() - 24.0
            baseline = self.height() * 0.58
            painter.setPen(QPen(QColor("#2d3a45"), 1))
            painter.drawLine(QPointF(left, baseline), QPointF(right, baseline))
            for beat in self.beats:
                x = left + (right - left) * beat / self.duration
                is_downbeat = any(abs(beat - downbeat) < 0.012 for downbeat in self.downbeats)
                active = abs(beat - self.position) < 0.09
                color = QColor("#f37f6b") if is_downbeat else QColor("#43c6b7")
                if active:
                    color = QColor("#ffffff")
                radius = 9.0 if is_downbeat else 5.0
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QRectF(x - radius, baseline - radius, radius * 2, radius * 2))
            progress_x = left + (right - left) * min(self.position / self.duration, 1.0)
            painter.setPen(QPen(QColor("#f6c85f"), 2))
            painter.drawLine(QPointF(progress_x, 24), QPointF(progress_x, self.height() - 28))
            painter.setPen(QColor("#82909d"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(QPointF(left, 22), "DOWNBEAT")
            painter.setPen(QColor("#43c6b7"))
            painter.drawText(QPointF(left + 86, 22), "BEAT")


class BeatWindow(QMainWindow):
    def __init__(self, data_root: Path) -> None:
        super().__init__()
        self.songs = load_songs(data_root / "audio")
        self.song: Song | None = None
        self.last_beat_index = -1
        self.setWindowTitle("Beat Room")
        self.resize(1120, 700)
        self._build_audio()
        self._build_ui()
        self._refresh_songs()

    def _build_audio(self) -> None:
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.78)
        self.click = QSoundEffect(self)
        self.click.setSource(QUrl.fromLocalFile(make_click()))
        self.click.setLoopCount(1)
        self.click.setVolume(0.65)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(300)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(24, 28, 18, 22)
        title = QLabel("BEAT ROOM")
        title.setObjectName("brand")
        side.addWidget(title)
        subtitle = QLabel("Choose a track to practice")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(24)
        self.song_list = QListWidget()
        self.song_list.setObjectName("songList")
        self.song_list.currentRowChanged.connect(self._song_selected)
        side.addWidget(self.song_list)
        self.library_state = QLabel()
        self.library_state.setObjectName("muted")
        side.addWidget(self.library_state)
        layout.addWidget(sidebar)

        content = QFrame()
        content.setObjectName("content")
        body = QVBoxLayout(content)
        body.setContentsMargins(42, 34, 42, 30)
        body.setSpacing(20)
        self.track_name = QLabel("Select a track")
        self.track_name.setObjectName("trackName")
        body.addWidget(self.track_name)
        self.track_meta = QLabel("Beat and downbeat timing will appear here")
        self.track_meta.setObjectName("muted")
        body.addWidget(self.track_meta)
        self.timeline = BeatTimeline()
        body.addWidget(self.timeline, 1)

        controls = QFrame()
        controls.setObjectName("controls")
        control_layout = QHBoxLayout(controls)
        control_layout.setContentsMargins(18, 15, 18, 15)
        self.play_button = QPushButton("PLAY")
        self.play_button.setObjectName("playButton")
        self.play_button.clicked.connect(self._toggle_play)
        control_layout.addWidget(self.play_button)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("timeLabel")
        control_layout.addWidget(self.time_label)
        control_layout.addStretch()
        self.audio_volume = self._volume_control("SONG", 78, self.audio_output.setVolume)
        control_layout.addWidget(self.audio_volume)
        self.click_volume = self._volume_control("METRONOME", 65, self.click.setVolume)
        control_layout.addWidget(self.click_volume)
        body.addWidget(controls)
        layout.addWidget(content, 1)
        self.setStyleSheet(STYLESHEET)

    def _volume_control(self, label: str, value: int, callback: object) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(10, 0, 0, 0)
        text = QLabel(label)
        text.setObjectName("volumeLabel")
        row.addWidget(text)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.setFixedWidth(120)
        slider.valueChanged.connect(lambda level: callback(level / 100))
        row.addWidget(slider)
        return widget

    def _refresh_songs(self) -> None:
        self.song_list.clear()
        for song in self.songs:
            item = QListWidgetItem(song.audio.stem)
            item.setData(Qt.ItemDataRole.UserRole, song)
            self.song_list.addItem(item)
        self.library_state.setText(f"{len(self.songs)} TRACKS  ·  data/audio")
        if self.songs:
            self.song_list.setCurrentRow(0)
        else:
            self.library_state.setText("No matching audio + JSON pairs found")

    def _song_selected(self, row: int) -> None:
        if row < 0:
            return
        self.player.stop()
        self.last_beat_index = -1
        self.song = self.song_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.player.setSource(QUrl.fromLocalFile(str(self.song.audio)))
        self.track_name.setText(self.song.audio.stem)
        self.track_meta.setText(
            f"{len(self.song.beats)} beats  ·  {len(self.song.downbeats)} downbeats"
        )
        self.timeline.set_data(self.song)
        self.play_button.setText("PLAY")

    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText("PLAY")
        elif self.song:
            self.player.play()
            self.play_button.setText("PAUSE")

    def _duration_changed(self, duration: int) -> None:
        self.timeline.duration = max(duration / 1000, self.timeline.duration)

    def _position_changed(self, position: int) -> None:
        seconds = position / 1000
        if (
            self.timeline.beats
            and self.last_beat_index >= 0
            and seconds < self.timeline.beats[self.last_beat_index] - 0.15
        ):
            self.last_beat_index = -1
        self.timeline.set_position(seconds)
        duration = max(self.player.duration() / 1000, 0)
        self.time_label.setText(f"{_clock(seconds)} / {_clock(duration)}")
        for index, beat in enumerate(self.timeline.beats):
            if beat > seconds + 0.025:
                break
            if index > self.last_beat_index:
                self.last_beat_index = index
                self.click.play()

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_button.setText("PLAY")
            self.last_beat_index = -1


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def main() -> int:
    app = QApplication([])
    app.setApplicationName("Beat Room")
    window = BeatWindow(Path.cwd() / "data")
    window.show()
    return app.exec()


STYLESHEET = """
QMainWindow, QWidget#content { background: #0d1319; color: #e9f0f2; }
QFrame#sidebar { background: #101a22; border-right: 1px solid #26333e; }
QLabel#brand { color: #f6c85f; font-size: 18px; font-weight: 800; }
QLabel#trackName { color: #f2f6f7; font-size: 28px; font-weight: 700; }
QLabel#muted { color: #82909d; font-size: 12px; }
QListWidget#songList {
    background: transparent; border: 0; outline: 0;
    color: #bdc8ce; font-size: 14px;
}
QListWidget#songList::item { padding: 13px 12px; border-radius: 6px; margin: 2px 0; }
QListWidget#songList::item:hover { background: #1b2a33; }
QListWidget#songList::item:selected { background: #173b3b; color: #73e0cf; }
QFrame#controls { background: #151f27; border: 1px solid #26333e; border-radius: 8px; }
QPushButton#playButton {
    background: #43c6b7; color: #09211f; border: 0; border-radius: 5px;
    padding: 11px 25px; font-weight: 800;
}
QPushButton#playButton:hover { background: #67d8c9; }
QPushButton#playButton:pressed { background: #2fa89b; }
QLabel#timeLabel { color: #f6c85f; font-size: 13px; font-weight: 700; min-width: 105px; }
QLabel#volumeLabel { color: #82909d; font-size: 10px; font-weight: 700; }
QSlider::groove:horizontal { height: 4px; background: #2b3943; border-radius: 2px; }
QSlider::handle:horizontal { width: 13px; margin: -5px 0; border-radius: 6px; background: #43c6b7; }
"""


if __name__ == "__main__":
    raise SystemExit(main())
