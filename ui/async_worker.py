# -*- coding: utf-8 -*-
from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


# Registro de workers activos. CRÍTICO: QThreadPool.start(worker) NO conserva una
# referencia Python al worker; si el llamador lo crea como variable local (lo
# habitual), el recolector de basura puede destruir el worker y su objeto de
# señales ANTES de que el hilo entregue el resultado → la señal 'result' se
# pierde en silencio (p. ej. la tabla de productos queda en blanco). Al guardar
# el worker aquí lo mantenemos vivo hasta que emite 'finished' (que llega al
# hilo principal DESPUÉS de 'result'), momento en el que se descarta.
_workers_activos = set()


class FunctionWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        _workers_activos.add(self)
        self.signals.finished.connect(self._al_terminar)

    def _al_terminar(self):
        _workers_activos.discard(self)

    @Slot()
    def run(self):
        # Ejecutar la función y emitir el resultado por separado, para no
        # confundir un error de la función con un error al emitir la señal.
        try:
            resultado = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            self._safe_emit(self.signals.error, str(exc))
        else:
            self._safe_emit(self.signals.result, resultado)
        finally:
            self._safe_emit(self.signals.finished)

    @staticmethod
    def _safe_emit(signal, *payload):
        # Si el objeto dueño de la señal ya fue destruido (la ventana o el
        # diálogo se cerró mientras el worker seguía en 2º plano), emit() lanza
        # RuntimeError. En ese caso no hay a quién notificar: se ignora.
        try:
            signal.emit(*payload)
        except RuntimeError:
            pass
