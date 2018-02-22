#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
# PURPOSE
Timeline View using QGraphicsView and its kin
Assume X coordinate corresponds to seconds, apply transforms as needed

# FUNCTION
- display a Scene of Timelines of Frames
- View is scrollable in time (screen X) and level (screen Y), compressible in time
- Timelines have logical Z order, with 0 being topmost and +n being bottom; top to bottom corresponds to screen position
- Timelines can be dragged and dropped to change their Z order, similar to layer list but including multiple Frames
- Frames represent individual visible dataset/image
- Frames may exist in the application only as metadata and can be in multiple states depending on user direction:

# ACTIONS to support
- drag a track up or down the z order
- pop a context menu for a track or a frame
- tool tips for frames or tracks
- change display state of frame, represented by color (see TimelineFrameState)
- allow one or more tracks to be selected 
- allow one or more frames to be selected
- scroll left and right to follow playback animation in background
- display time axis with actual dates and times, including click-to-place
- scroll vertically (when more tracks than can be shown in View)
- display movable and live-updated time cursor (playhead), including highlighting borders of frames under time cursor
- signal playhead movement to external agencies
- jump playhead to arbitrary time, optionally using left-right arrow keys
    + when track/s or frames selected, jump to next/last frame transition within the selection
    + when no tracks selected, consider all available frames (may require document help)
- change horizontal seconds-per-pixel (generally done with an external slider or mouse alt-drag on time scale)
- permit dragging of colorbars between layers
- permit dragging of colorbars off an external palette
- allow selection of tracks and frames using metadata matching
- allow circulation of z-order using up/down arrow keys
- allow sorting of tracks based on metadata characteristics
- future: nested tracks, e.g. for RGB or Algebraic

# CONCEPTS and VOCABULARY with respect to SIFT
A timeline Frame represents a Product in the Workspace
A timeline Track in the timeline represents a time series of related Products
The Scene represents a combination of the Metadatabase and (to a lesser extent) the active Document
Stepping into wider application-wide scope:
Products may or may not have Content cached in the workspace
ActiveContent in the workspace is being used to feed the SceneGraph by the SceneGraphManager
The Workspace has a Metadatabase of Resource, Product and Content metadata
The Document holds user intent, including EngineRules for producing Product Content
The Engine performs operations on the Workspace and its Metadatabase to maintain implicit Product Content

# REFERENCES
http://doc.qt.io/archives/qt-4.8/examples-graphicsview.html
http://doc.qt.io/archives/qt-4.8/qt-graphicsview-diagramscene-example.html
http://pyqt.sourceforge.net/Docs/PyQt4/qgraphicsscene.html
http://doc.qt.io/qt-4.8/qgraphicsview.html
http://doc.qt.io/qt-4.8/qgraphicsitemgroup.html
http://pyqt.sourceforge.net/Docs/PyQt4/qgraphicsitem.html
http://doc.qt.io/qt-5/qtwidgets-graphicsview-dragdroprobot-example.html
http://pyqt.sourceforge.net/Docs/PyQt4/qgraphicsobject.html
http://pyqt.sourceforge.net/Docs/PyQt4/qpainter.html
https://stackoverflow.com/questions/4216139/python-object-in-qmimedata

:author: R.K.Garcia <rkgarcia@wisc.edu>
:copyright: 2017 by University of Wisconsin Regents, see AUTHORS for more details
:license: GPLv3, see LICENSE for more details
"""
from uuid import UUID
from typing import Mapping, Any
from weakref import ref
from PyQt4.QtCore import Qt
from PyQt4.QtGui import *

from sift.view.TimelineCommon import *

LOG = logging.getLogger(__name__)


class QTrackItem(QGraphicsObject):
    """ A group of Frames corresponding to a timeline
    This allows drag and drop of timelines to be easier
    """
    frames = None  # Iterable[QFrameItem], maintained privately between track and frame
    _scene = None  # weakref to scene
    _scale: TimelineCoordTransform = None
    _uuid: UUID = None
    _z: int = None  # our track number as displayed, 0 being highest on screen, with larger Z going downward
    _title: str = None
    _subtitle: str = None
    _icon: QIcon = None   # e.g. whether it's algebraic or RGB
    _metadata: Mapping = None  # arbitrary key-value store for selecting by metadata; in our case this often includes item family for seleciton
    _tooltip: str = None
    _color: QColor = None
    _selected: bool = False
    _colormap: [QGradient, QImage, QPixmap] = None
    _min: float = None
    _max: float = None
    _dragging: bool = False   # whether or not a drag is in progress across this item
    _left_pad: timedelta = timedelta(hours=1)  # space to left of first frame which we reserve for labels etc
    _right_pad: timedelta = timedelta(minutes=5)  # space to right of last frame we reserve for track closing etc
    # position in scene coordinates is determined by _z level and starting time of first frame, minus _left_pad
    _bounds: QRectF = QRectF()  # bounds of the track in scene coordinates, assuming 0,0 corresponds to vertical center of left edge of frame representation
    _gi_title: QGraphicsTextItem = None
    _gi_subtitle: QGraphicsTextItem = None
    _gi_icon: QGraphicsPixmapItem = None
    _gi_colormap: QGraphicsPixmapItem = None

    def __init__(self, scene, scale: TimelineCoordTransform, uuid: UUID, z: int,
                 title: str, subtitle: str = None, icon: QIcon = None, metadata: dict = None,
                 tooltip: str = None, color: QColor = None, selected: bool = False,
                 colormap: [QGradient, QImage] = None, min: float = None, max: float = None):
        super(QTrackItem, self).__init__()
        self.frames = []
        self._scene = ref(scene)
        self._scale = scale
        self._uuid = uuid
        self._z = z
        self._title = title
        self._subtitle = subtitle
        self._icon = icon
        self._metadata = metadata or {}
        self._tooltip = tooltip
        self._color = color
        self._selected = selected
        self._colormap = colormap
        self._min, self._max = min, max
        # pen, brush = scene.default_track_pen_brush
        # if pen:
        #     LOG.debug('setting pen')
        #     self.setPen(pen)
        # if brush:
        #     LOG.debug('setting brush')
        #     self.setBrush(brush)
        self.update_pos_bounds()
        self._add_decorations()
        scene.addItem(self)
        self.setAcceptDrops(True)

    @property
    def uuid(self):
        return self._uuid

    @property
    def z(self):
        return self._z

    @z.setter
    def z(self, new_z: int):
        self._z = new_z

    def scene(self):
        return self._scene()

    @property
    def default_frame_pen_brush(self):
        return self.scene().default_frame_pen_brush

    def _add_decorations(self):
        """Add decor sub-items to self
        title, subtitle, icon, colormap
        these are placed left of the local origin inside the _left_pad area
        """
        scene = self.scene()
        if self._title:
            self._gi_title = it = scene.addSimpleText(self._title)
            it.setParentItem(self)
        if self._subtitle:
            self._gi_subtitle = it = scene.addSimpleText(self._subtitle)
            it.setParentItem(self)
        # FUTURE: add draggable color-map pixmap

    # commands to cause item updates and then propagate back to the scene

    def set_colormap(self, cmap: mimed_colormap):
        """Inform scene that the user wants all tracks in our family to use this colormap
        """
        LOG.warning("set colormap from dragged colormap not yet implemented")

    def insert_track_before(self, track: mimed_track):
        """Inform scene that user wants a dragged scene moved to before us in the z-order"""
        LOG.warning("reorder tracks usingdragged track not yet implemented")

    # painting and boundaries

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget=None):
        super(QTrackItem, self).paint(painter, option, widget)

    def boundingRect(self) -> QRectF:
    #     if self._bounds is None:
    #         return self.update_pos_and_bounds()
        return self._bounds

    # click events / drag departures

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        LOG.debug("QTrackItem mouse-down")
        return super(QTrackItem, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        LOG.debug("QTrackItem mouse-up")
        return super(QTrackItem, self).mouseReleaseEvent(event)

    # handle drag and drop arrivals

    def dragEnterEvent(self, event: QGraphicsSceneDragDropEvent):
        self._dragging = True

        # test the content being dragged to see if it's compatible; if so, accept event
        mime = event.mimeData()
        if mime.hasFormat(MIMETYPE_TIMELINE_COLORMAP):
            event.setAccepted(True)
        elif mime.hasFormat(MIMETYPE_TIMELINE_TRACK):
            # FIXME: implement animated re-arrange of tracks
            event.setAccepted(True)
        else:
            event.setAccepted(False)

    def dragLeaveEvent(self, event: QGraphicsSceneDragDropEvent):
        self._dragging = False

    def dropEvent(self, event: QGraphicsSceneDragDropEvent):
        colormap = recv_mime(event, MIMETYPE_TIMELINE_COLORMAP)
        if colormap is not None:
            self.set_colormap(colormap)
            return
        new_track_before = recv_mime(event, MIMETYPE_TIMELINE_TRACK)
        if new_track_before is not None:
            self.insert_track_before(new_track_before)
        content = pkl.loads(event.mimeData().data())
        event.setAccepted(False)

    # working with Frames as sub-items, updating and syncing position and extents

    def _iter_frame_children(self):
        return list(self.frames)
        # children = tuple(self.childItems())
        # # LOG.debug("{} children".format(len(children)))
        # for child in children:
        #     if isinstance(child, QFrameItem):
        #         yield child

    def time_extent_of_frames(self):
        """start time and duration of the frames held by the track
        """
        s, e = None, None
        for child in self._iter_frame_children():
            # y relative to track is 0
            # calculate absolute x position in scene
            # assert (child.uuid != self.uuid)
            t,d = child.td
            s = t if (s is None) else min(t, s)
            e = (t + d) if (e is None) else max(e, t + d)
        if e is None:
            LOG.info("empty track cannot determine its horizontal extent")
            return None, None
        return s, e - s

    def update_pos_bounds(self):
        """Update position and bounds of the Track to reflect current TimelineCoordTransform, encapsulating frames owned
        Note that the local x=0.0 corresponds to the time of the first frame in the track
        This is also the center of rotation or animation "handle" (e.g. for track dragging)
        """
        # starting time and duration of the track, computed from frames owned
        t, d = self.time_extent_of_frames()
        if (t is None) or (d is None):
            LOG.debug("no frames contained, cannot adjust size or location of QTrackItem")
            return
        # scene y coordinate of upper left corner
        top = self._z * DEFAULT_TRACK_HEIGHT
        # convert track extent to scene coordinates using current transform
        frames_left, frames_width = self._scale.calc_pixel_x_pos(t, d)
        track_left, track_width = self._scale.calc_pixel_x_pos(t - self._left_pad, d + self._left_pad + self._right_pad)
        # set track position, assuming we want origin coordinate of track item to be centered vertically within item
        self.prepareGeometryChange()
        self.setPos(frames_left, top + DEFAULT_TRACK_HEIGHT / 2)
        # bounds relative to position in scene, left_pad space to left of local origin (x<0), frames and right-pad at x>=0
        self._bounds = QRectF(track_left - frames_left, -DEFAULT_TRACK_HEIGHT / 2, track_width, DEFAULT_TRACK_HEIGHT)

    def update_frame_positions(self, *frames):
        """Update frames' origins relative to self after TimelineCoordTransform has changed scale
        """
        myx = self.pos().x()  # my x coordinate relative to scene
        frames = tuple(frames) or self._iter_frame_children()
        for frame in frames:
            # y relative to track is 0
            # calculate absolute x position in scene
            x, _ = self._scale.calc_pixel_x_pos(frame.t)
            frame.prepareGeometryChange()
            frame.setPos(x - myx, 0.0)


class QFrameItem(QGraphicsObject):
    """A Frame
    For SIFT use, this corresponds to a single Product or single composite of multiple Products (e.g. RGB composite)
    QGraphicsView representation of a data frame, with a start and end time relative to the scene.
    Essentially a frame sprite
    """
    _state: TimelineFrameState = None
    _track = None  # weakref to track we belong to
    _scale: TimelineCoordTransform = None
    _uuid: UUID = None
    _start: datetime = None
    _duration: timedelta = None
    _title: str = None
    _subtitle: str = None
    _thumb: QPixmap = None
    _metadata: Mapping = None
    _bounds: QRectF = QRectF()

    def __init__(self, track: QTrackItem, scale: TimelineCoordTransform, uuid: UUID,
                 start: datetime, duration: timedelta, state: TimelineFrameState,
                 title: str, subtitle: str = None, thumb: QPixmap = None,
                 metadata: Mapping[str, Any] = None):
        """create a frame representation and add it to a timeline
        Args:
            track: which timeline to add it to
            state: initial state
            start: frame start time
            duration: frame duration
            title: title of frame
            subtitle: subtitle (below title, optional)
            thumb: thumbnail image (via pillow), optional, may not be displayed if space is not available
            uuid: UUID of workspace representation
        """
        super(QFrameItem, self).__init__()
        self._track = ref(track)
        self._state = state
        self._scale = scale
        self._start = start
        self._duration = duration
        self._title = title
        self._subtitle = subtitle
        self._thumb = thumb
        self._metadata = metadata
        self._uuid = uuid
        # self._pen, self._brush = track.default_frame_pen_brush
        # if pen:
        #     LOG.debug('setting pen')
        #     self.setPen(pen)
        # if brush:
        #     LOG.debug('setting brush')
        #     self.setBrush(brush)
        track.frames.append(self)
        self.setParentItem(track)
        self.update_bounds()
        track.update_pos_bounds()
        track.update_frame_positions()
        # self.setAcceptDrops(True)

    @property
    def uuid(self):
        return self._uuid

    @property
    def t(self):
        return self._start

    @property
    def d(self):
        return self._duration

    @property
    def td(self):
        return self._start, self._duration

    @property
    def track(self):
        return self._track()

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        if new_state != self._state:
            self._state = new_state
            self.update()

    # painting and boundaries

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget=None) -> None:
        pen, brush = self.track.default_frame_pen_brush
        rect = self.boundingRect()
        painter.setBrush(brush)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, DEFAULT_FRAME_CORNER_RADIUS, DEFAULT_FRAME_CORNER_RADIUS, Qt.RelativeSize)
        # super(QFrameItem, self).paint(painter, option, widget)

    def boundingRect(self) -> QRectF:
        """return relative bounding rectangle, given position is set by Track parent as needed
        """
        LOG.debug("frame boundingRect")
        return self._bounds

    # internal recalculation / realignment

    def update_bounds(self):
        """set size and width based on current scaling
        position is controlled by the track, since we have to be track-relative
        """
        left = 0.0
        top = - DEFAULT_FRAME_HEIGHT / 2
        height = DEFAULT_FRAME_HEIGHT
        width = self._scale.calc_pixel_duration(self._duration)
        LOG.debug("width for {} is {} scene pixels".format(self._duration, width))
        old_bounds = self._bounds
        new_bounds = QRectF(left, top, width, height)
        if (old_bounds is None) or (new_bounds != old_bounds):
            self.prepareGeometryChange()
            self._bounds = new_bounds

    # # handle drag and drop
    # def dragEnterEvent(self, event: QGraphicsSceneDragDropEvent):
    #     event.setAccepted(False)
    #
    # def dragLeaveEvent(self, event: QGraphicsSceneDragDropEvent):
    #     event.setAccepted(False)
    #
    # def dropEvent(self, event: QGraphicsSceneDragDropEvent):
    #     event.setAccepted(False)

    # handle clicking
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        LOG.debug("QFrameItem mouse-down")
        return super(QFrameItem, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        LOG.debug("QFrameItem mouse-up")
        return super(QFrameItem, self).mouseReleaseEvent(event)


class QTimeRulerItem(QGraphicsRectItem):
    """A ruler object showing the time dimension, an instance of which is at the top, bottom, or both ends of the Scene"""

    def __init__(self):
        super(QTimeRulerItem, self).__init__()

