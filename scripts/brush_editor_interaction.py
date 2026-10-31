"""Shared rectangle selection and grouped dragging for the native brush editors."""
import numpy as np
from PyQt5 import QtCore
import pyqtgraph as pg


class SelectionViewBox(pg.ViewBox):
    rectangleSelected=QtCore.pyqtSignal(object,bool)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.box_select=False
        self.outline=pg.PlotDataItem(pen=pg.mkPen('#2563eb',width=1,style=QtCore.Qt.DashLine))
        self.outline.setZValue(100);self.addItem(self.outline,ignoreBounds=True)

    def mouseDragEvent(self,event,axis=None):
        if event.button()==QtCore.Qt.LeftButton and (self.box_select or event.modifiers() & QtCore.Qt.ShiftModifier):
            event.accept()
            start=self.mapSceneToView(event.buttonDownScenePos());end=self.mapSceneToView(event.scenePos())
            x0,x1=sorted([start.x(),end.x()]);y0,y1=sorted([start.y(),end.y()])
            self.outline.setData([x0,x1,x1,x0,x0],[y0,y0,y1,y1,y0])
            if event.isFinish():
                self.outline.setData([],[])
                self.rectangleSelected.emit((x0,x1,y0,y1),bool(event.modifiers() & QtCore.Qt.ControlModifier))
        else:super().mouseDragEvent(event,axis=axis)


class DraggablePoint(pg.TargetItem):
    dragStarted=QtCore.pyqtSignal(object)
    pointClicked=QtCore.pyqtSignal(object,bool)

    def mouseDragEvent(self,event):
        if event.button()==QtCore.Qt.LeftButton and event.isStart():self.dragStarted.emit(self)
        super().mouseDragEvent(event)

    def mouseClickEvent(self,event):
        if event.button()==QtCore.Qt.LeftButton:
            event.accept();self.pointClicked.emit(self,bool(event.modifiers() & QtCore.Qt.ControlModifier))
        else:super().mouseClickEvent(event)


def selected_in_rect(points,bounds):
    points=np.asarray(points,float);x0,x1,y0,y1=bounds
    return set(np.flatnonzero((points[:,0]>=x0)&(points[:,0]<=x1)&(points[:,1]>=y0)&(points[:,1]<=y1)).tolist())


def shifted_speeds(values,indices,delta,upper):
    """Clamp the common delta, preserving spacing between all selected speeds."""
    values=np.asarray(values,float);indices=np.array(sorted(indices),int)
    if not len(indices):return values.copy()
    delta=float(np.clip(delta,.05-values[indices].min(),upper-values[indices].max()))
    result=values.copy();result[indices]+=delta
    return result
