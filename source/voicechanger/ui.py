import json
import threading
from pathlib import Path
import torch
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QUrl
from PySide6.QtGui import QColor,QDesktopServices,QFont,QIcon,QPainter,QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,
    QPushButton,QComboBox,QTabWidget,QFormLayout,QSlider,QCheckBox,QProgressBar,QMessageBox,
    QFileDialog,QTextEdit,QSystemTrayIcon,QMenu,QInputDialog,QSpinBox,QScrollArea)
from .config import Settings,MODES,PROFILES,user_dir
from .native import NativeAudio,virtual_output
from .paths import native_path,application_root
from .engine import AudioWorker
from .diagnostics import hardware
from .convert import convert_file
from .hotkeys import GlobalHotkeys

STYLE='''
QWidget {background:#101218;color:#e6e8f0;font-family:"Segoe UI";font-size:14px;}
QTabWidget::pane {border:1px solid #282d3b;border-radius:12px;padding:14px;}
QTabBar::tab {padding:11px 18px;color:#979fb4;border-bottom:2px solid transparent;}
QTabBar::tab:selected {color:#c2b5ff;border-bottom:2px solid #a08afb;}
QComboBox,QSpinBox,QTextEdit {background:#1c202c;border:1px solid #33394c;border-radius:7px;padding:6px;}
QComboBox,QSpinBox {min-height:24px;}
QComboBox QAbstractItemView {background:#1c202c;selection-background-color:#4f4078;}
QPushButton {background:#282e40;border:1px solid #3c455d;border-radius:8px;padding:9px 16px;}
QPushButton:hover {background:#363f57;}
QPushButton:disabled,QComboBox:disabled,QSpinBox:disabled {color:#626b81;background:#181c26;}
QPushButton#start {background:#a58afa;color:#171127;font-size:19px;font-weight:600;padding:16px;}
QPushButton#start:disabled {background:#4b4166;color:#b7b0c8;}
QProgressBar {background:#242a37;border:0;border-radius:4px;max-height:9px;}
QProgressBar::chunk {background:#a58afa;border-radius:4px;}
QSlider::groove:horizontal {height:5px;background:#30374a;border-radius:2px;}
QSlider::handle:horizontal {background:#b9a1ff;width:14px;margin:-5px 0;border-radius:7px;}
QCheckBox {spacing:9px;padding:5px 0;}
QLabel#muted {color:#a2abc0;}
'''


class Job(QThread):
    done=Signal(object);failed=Signal(str);progress=Signal(str)
    def __init__(self,fn):super().__init__();self.fn=fn;self.cancel=threading.Event()
    def run(self):
        try:self.done.emit(self.fn())
        except Exception as error:self.failed.emit(str(error))


def icon(active=False):
    pix=QPixmap(64,64);pix.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#a58afa' if active else '#525d76'));painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4,4,56,56,17,17);painter.setPen(QColor('#171127'))
    painter.setFont(QFont('Segoe UI',30,QFont.Weight.Bold));painter.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,'V');painter.end()
    return QIcon(pix)


class DeviceCombo(QComboBox):
    def showPopup(self):
        refresh=getattr(self,'refresh_callback',None)
        if refresh:refresh()
        super().showPopup()


class AdvancedWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle('AI Voice Changer · CUDA / WAV');self.setWindowIcon(icon())
        bounds=QApplication.primaryScreen().availableGeometry()
        self.resize(min(900,bounds.width()-40),min(900,bounds.height()-60))
        self.setMinimumSize(min(760,bounds.width()-40),min(650,bounds.height()-60))
        try:self.settings=Settings.load()
        except Exception:self.settings=Settings()
        self.cuda_available=torch.cuda.is_available();self.worker=None;self.offline_job=None
        self.jobs=[];self.quitting=False;self.error_text='';self.hardware={};self.last_output=''
        self.editing_profile=False
        self.native=NativeAudio(native_path());self.devices=[];self.custom_profiles={}
        try:
            value=json.loads((user_dir()/'profiles.json').read_text(encoding='utf-8'))
            if isinstance(value,dict):
                for name,data in value.items():
                    if not isinstance(name,str) or not name or name in PROFILES or not isinstance(data,dict):continue
                    try:
                        fields={key:data[key] for key in ('softness','volume','noise_gate_db','pitch','auto_pitch','target_low','target_high') if key in data}
                        Settings(**fields).validate()
                        if not isinstance(fields.get('auto_pitch',True),bool):continue
                        self.custom_profiles[name]=fields
                    except (ValueError,TypeError):continue
        except (OSError,ValueError):pass
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root);layout.setContentsMargins(28,22,28,22);layout.setSpacing(15)
        title=QLabel('AI Voice Changer');title.setStyleSheet('font-size:27px;font-weight:600;');layout.addWidget(title)
        subtitle=QLabel('Мужской → женский · локальная нейросетевая конверсия');subtitle.setObjectName('muted');layout.addWidget(subtitle)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.build_main();self.build_voice();self.build_models();self.build_diagnostics()
        self.status_label=QLabel('Остановлено · микрофон выключен');self.status_label.setWordWrap(True);layout.addWidget(self.status_label)
        self.tray=QSystemTrayIcon(icon(),self);menu=QMenu()
        for label,callback in [('Открыть',self.showNormal),('Запуск / остановка',self.primary_action),
                               ('Отключить выход',self.emergency_stop),('Проверить обновления',self.check_updates),('Завершить',self.quit_app)]:
            menu.addAction(label).triggered.connect(callback)
        self.tray.setContextMenu(menu);self.tray.setToolTip('AI Voice Changer · микрофон выключен')
        self.tray.activated.connect(lambda reason:self.showNormal() if reason==QSystemTrayIcon.ActivationReason.Trigger else None);self.tray.show()
        self.hotkeys=GlobalHotkeys([self.primary_action,lambda:self.mute.toggle(),self.next_profile,lambda:self.monitor.toggle()])
        QApplication.instance().installNativeEventFilter(self.hotkeys)
        self.refresh_devices();self.apply_settings(self.settings)
        self.profile.currentTextChanged.connect(self.select_profile)
        self.model_choice.currentIndexChanged.connect(self.update_availability);self.compute.currentIndexChanged.connect(self.update_availability)
        for field in (self.volume,self.softness,self.gate,self.pitch,self.target_low,self.target_high):field.valueChanged.connect(self.queue_voice)
        self.auto_pitch.toggled.connect(self.queue_voice)
        self.update_availability();QTimer.singleShot(150,self.inspect_hardware)

    def scroll_tab(self,page,title):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame);scroll.setWidget(page)
        self.tabs.addTab(scroll,title)

    def build_main(self):
        page=QWidget();box=QVBoxLayout(page);box.setSpacing(13)
        self.mode_note=QLabel();self.mode_note.setWordWrap(True);self.mode_note.setStyleSheet('color:#d4bd86;');box.addWidget(self.mode_note)
        form=QFormLayout();form.setSpacing(9)
        self.model_choice=QComboBox();self.model_choice.addItem('Seed-VC · основной','seed');self.model_choice.addItem('RVC · управление F0','rvc')
        self.profile=QComboBox();self.profile.addItems([*PROFILES,*self.custom_profiles])
        self.mode=QComboBox();self.mode.addItems(MODES)
        self.mic=DeviceCombo();self.output=DeviceCombo();self.headphones=QComboBox()
        for text,field in [('Нейросеть',self.model_choice),('Профиль',self.profile),('Качество',self.mode),
                           ('Микрофон',self.mic),('Виртуальный выход',self.output),('Наушники',self.headphones)]:form.addRow(text,field)
        if not self.cuda_available:
            for field in (self.mic,self.output,self.headphones):field.hide();form.labelForField(field).hide()
        box.addLayout(form)
        self.start=QPushButton();self.start.setObjectName('start');self.start.clicked.connect(self.primary_action);box.addWidget(self.start)
        self.file_progress=QProgressBar();self.file_progress.setRange(0,1);self.file_progress.setValue(0);self.file_progress.setTextVisible(False);box.addWidget(self.file_progress)
        self.input_meter=QProgressBar();self.output_meter=QProgressBar()
        meters=QWidget();meter_form=QFormLayout(meters)
        for text,field in [('Вход',self.input_meter),('Выход',self.output_meter)]:
            field.setRange(0,100);field.setValue(0);field.setTextVisible(False);meter_form.addRow(text,field)
        meters.setVisible(self.cuda_available);box.addWidget(meters)
        row=QWidget();toggles=QHBoxLayout(row)
        self.monitor=QCheckBox('Слышать в наушниках');self.mute=QCheckBox('Отключить микрофон и выход')
        self.monitor.toggled.connect(self.toggle_monitor);self.mute.toggled.connect(self.toggle_mute)
        toggles.addWidget(self.monitor);toggles.addWidget(self.mute);row.setVisible(self.cuda_available);box.addWidget(row)
        self.record=QCheckBox('Явно записать исходный и обработанный звук в WAV в этом запуске')
        self.record.setChecked(False);self.record.setVisible(self.cuda_available);box.addWidget(self.record)
        self.timing=QLabel('Сквозная задержка: не измерена');self.timing.setWordWrap(True);box.addWidget(self.timing)
        controls=QHBoxLayout();self.refresh=QPushButton('Обновить устройства');self.refresh.clicked.connect(self.refresh_devices)
        setup=QPushButton('Подключение к Discord');setup.clicked.connect(self.setup_guide)
        controls.addWidget(self.refresh);controls.addWidget(setup);box.addLayout(controls)
        self.route=QLabel();self.route.setWordWrap(True);self.route.setObjectName('muted');box.addWidget(self.route)
        note=QLabel('Оценка естественности и двухчасовой тест на NVIDIA ещё не пройдены. '
                    'При старте приложения микрофон не включается.');note.setWordWrap(True);note.setObjectName('muted');box.addWidget(note)
        keys=QLabel('Ctrl+Alt+F9 запуск/стоп · F10 микрофон · F11 профиль · F12 наушники');keys.setWordWrap(True);keys.setObjectName('muted');box.addWidget(keys)
        box.addStretch();self.scroll_tab(page,'Главная')

    def build_voice(self):
        page=QWidget();box=QVBoxLayout(page);form=QFormLayout();form.setSpacing(14)
        self.volume=QSlider(Qt.Orientation.Horizontal);self.volume.setRange(0,200)
        self.softness=QSlider(Qt.Orientation.Horizontal);self.softness.setRange(0,100)
        self.gate=QSlider(Qt.Orientation.Horizontal);self.gate.setRange(-90,-25)
        self.compute=QComboBox();self.compute.addItem('Автоматически','auto');self.compute.addItem('CPU · файлы','cpu')
        if self.cuda_available:self.compute.addItem('CUDA','cuda')
        self.threads=QSpinBox();self.threads.setRange(1,16)
        self.auto_pitch=QCheckBox('Адаптация под исходный голос')
        self.pitch=QSlider(Qt.Orientation.Horizontal);self.pitch.setRange(-12,12)
        self.target_low=QSpinBox();self.target_low.setRange(80,590)
        self.target_high=QSpinBox();self.target_high.setRange(90,600)
        for text,field in [('Громкость · 0–200%',self.volume),('Мягкость',self.softness),('Мягкий шумовой порог · dB',self.gate),
                           ('Вычисления',self.compute),('Потоки CPU',self.threads),('Auto Pitch · RVC',self.auto_pitch),
                           ('Pitch · RVC · −12…+12 полутонов',self.pitch),('Целевой F0 от · Hz',self.target_low),('Целевой F0 до · Hz',self.target_high)]:form.addRow(text,field)
        box.addLayout(form);self.values=QLabel();self.values.setWordWrap(True);box.addWidget(self.values)
        text=QLabel('F0 регулируется внутри нейросетевой модели RVC, с сохранением направления интонационного контура. '
                    'Для Seed-VC эти регуляторы недоступны: голос задаётся разрешённым женским эталоном.\n\n'
                    'Soft Female использует ту же женскую модель и мягкую выходную фильтрацию. '
                    'У Seed-VC режимы выполняют 4 / 10 / 20 шагов диффузии; также меняются контекст, буферы и фильтр ресэмплера.')
        text.setWordWrap(True);text.setObjectName('muted');box.addWidget(text)
        row=QHBoxLayout()
        for title,callback in [('Сохранить настройки',self.save_settings),('Свой профиль',self.save_profile),('Папка записей',self.open_recordings)]:
            button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        box.addLayout(row);box.addStretch();self.scroll_tab(page,'Настройки голоса')

    def build_models(self):
        page=QWidget();box=QVBoxLayout(page)
        text=QLabel('Seed-VC Tiny + XLS-R + HiFT — основной вариант для русской речи.\n'
                    'RVC v2 + ContentVec + RMVPE — вариант с управлением F0.\n\n'
                    'Компоненты проверяются по закреплённым SHA-256. Все вычисления локальные; '
                    'произвольный код из checkpoint не выполняется. Пользовательские модели не импортируются.\n\n'
                    'На этом компьютере можно конвертировать файлы на CPU. Живой микрофон использует только CUDA. '
                    'Исходящий необработанный голос при сбоях не подставляется.')
        text.setWordWrap(True);box.addWidget(text)
        self.offline=QPushButton('Преобразовать WAV-файл…');self.offline.clicked.connect(self.offline_convert);box.addWidget(self.offline)
        self.offline_status=QLabel('Файловый режим не использует микрофон.');self.offline_status.setWordWrap(True);box.addWidget(self.offline_status)
        self.play_file=QPushButton('Прослушать готовый WAV');self.play_file.setEnabled(False)
        self.play_file.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output)));box.addWidget(self.play_file)
        samples=QPushButton('Открыть контрольные примеры');samples.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(application_root()/'samples'))));box.addWidget(samples)
        box.addStretch();self.scroll_tab(page,'Нейросеть и WAV')

    def build_diagnostics(self):
        page=QWidget();box=QVBoxLayout(page);self.diagnostic=QTextEdit();self.diagnostic.setReadOnly(True);box.addWidget(self.diagnostic)
        button=QPushButton('Обновить диагностику');button.clicked.connect(self.inspect_hardware);box.addWidget(button);self.tabs.addTab(page,'Диагностика')

    def finish_job(self,job):
        if job in self.jobs:self.jobs.remove(job)
        job.fn=None;job.deleteLater()

    def inspect_hardware(self):
        job=Job(hardware);self.jobs.append(job)
        def done(data):
            self.hardware=data;self.diagnostic.setPlainText(json.dumps(data,ensure_ascii=False,indent=2)+
                '\n\nСквозная задержка не измерена. Время модели и задержка API устройств не равны ей.\n'+
                ('Заняты горячие клавиши: '+', '.join(self.hotkeys.unavailable) if self.hotkeys.unavailable else 'Горячие клавиши зарегистрированы.'))
        job.done.connect(done);job.failed.connect(self.status_label.setText);job.finished.connect(lambda:self.finish_job(job));job.start()

    def refresh_devices(self):
        if self.worker and self.worker.isRunning():return
        previous=[field.currentData() for field in (self.mic,self.output,self.headphones)]
        self.devices=self.native.devices()
        for field in (self.mic,self.output,self.headphones):field.clear()
        self.output.addItem('Не передавать во внешние приложения','');self.headphones.addItem('Выберите наушники','')
        virtual=[]
        for device in self.devices:
            if device['flow']=='capture' and not any(s in device['name'].lower() for s in ('cable output','voicemeeter')):
                self.mic.addItem(device['name'],device['id'])
            elif device['flow']=='render':
                if virtual_output(device):self.output.addItem(device['name'],device['id']);virtual.append(device)
                else:self.headphones.addItem(device['name'],device['id'])
        for field,value in zip((self.mic,self.output,self.headphones),previous):
            index=field.findData(value)
            if index>=0:field.setCurrentIndex(index)
        if virtual and not self.settings.output:self.output.setCurrentIndex(1)
        self.route.setText('В приложении выберите CABLE Input, в Discord / OBS — CABLE Output.' if virtual else
                           'VB-CABLE не найден. Для файловой конверсии он не требуется. Для Discord установите драйвер по инструкции.')

    def collect(self):
        return Settings(microphone=self.mic.currentData() or '',output=self.output.currentData() or '',headphones=self.headphones.currentData() or '',
            model=self.model_choice.currentData(),profile=self.profile.currentText(),mode=self.mode.currentText(),
            backend=self.compute.currentData(),threads=self.threads.value(),volume=self.volume.value()/100,softness=self.softness.value()/100,
            noise_gate_db=self.gate.value(),auto_pitch=self.auto_pitch.isChecked(),pitch=self.pitch.value(),
            target_low=self.target_low.value(),target_high=self.target_high.value()).validate()

    def apply_settings(self,cfg):
        for field,value in ((self.mic,cfg.microphone),(self.output,cfg.output),(self.headphones,cfg.headphones),(self.model_choice,cfg.model),(self.compute,cfg.backend)):
            index=field.findData(value)
            if index>=0:field.setCurrentIndex(index)
        self.profile.setCurrentText(cfg.profile);self.mode.setCurrentText(cfg.mode);self.threads.setValue(cfg.threads)
        self.volume.setValue(round(cfg.volume*100));self.softness.setValue(round(cfg.softness*100));self.gate.setValue(round(cfg.noise_gate_db))
        self.auto_pitch.setChecked(cfg.auto_pitch);self.pitch.setValue(round(cfg.pitch));self.target_low.setValue(round(cfg.target_low));self.target_high.setValue(round(cfg.target_high))
        self.update_values()

    def update_values(self):
        self.values.setText(f'Громкость {self.volume.value()}% · Мягкость {self.softness.value()}% · Порог {self.gate.value()} dB · Pitch {self.pitch.value():+d}')

    def update_availability(self,*_):
        live=bool(self.worker and self.worker.isRunning());busy=bool(self.offline_job)
        capable=self.cuda_available and self.compute.currentData()!='cpu'
        self.mode_note.setText('Живой режим · CUDA. Микрофон включается только после запуска и прогрева.' if capable else
            'Файловый режим · CPU. Микрофон не используется; конверсия может идти медленнее длительности записи.')
        for field in (self.model_choice,self.mode,self.compute,self.threads):field.setEnabled(not live and not busy)
        for field in (self.profile,self.volume,self.softness,self.gate):field.setEnabled(not busy)
        for field in (self.mic,self.output,self.headphones,self.record):field.setEnabled(capable and not live and not busy)
        for field in (self.monitor,self.mute):field.setEnabled(capable and not busy)
        for field in (self.auto_pitch,self.pitch,self.target_low,self.target_high):field.setEnabled(self.model_choice.currentData()=='rvc' and not busy)
        self.refresh.setEnabled(not live and not busy);self.offline.setEnabled(not live and not busy)
        self.start.setEnabled(True);self.start.setText('Отменить конверсию' if busy else 'Остановить' if live else 'Начать преобразование' if capable else 'Преобразовать WAV…')

    def queue_voice(self,*_):
        if self.editing_profile:return
        self.update_values()
        if self.worker and self.worker.isRunning():
            try:self.worker.update_voice(self.collect())
            except ValueError as error:self.status_label.setText(str(error))

    def select_profile(self,name):
        self.editing_profile=True
        if name in PROFILES:
            softness,volume=PROFILES[name];self.softness.setValue(round(softness*100));self.volume.setValue(round(volume*100))
        elif name in self.custom_profiles:
            data=self.custom_profiles[name]
            self.softness.setValue(round(data.get('softness',0)*100));self.volume.setValue(round(data.get('volume',1)*100));self.gate.setValue(round(data.get('noise_gate_db',-60)))
            self.pitch.setValue(round(data.get('pitch',0)));self.auto_pitch.setChecked(data.get('auto_pitch',True))
            self.target_low.setValue(round(data.get('target_low',165)));self.target_high.setValue(round(data.get('target_high',320)))
        self.editing_profile=False;self.queue_voice()

    def next_profile(self):
        if self.offline_job:return
        self.profile.setCurrentIndex((self.profile.currentIndex()+1)%self.profile.count())

    def save_settings(self):
        try:self.settings=self.collect();self.settings.save();self.status_label.setText('Настройки сохранены')
        except Exception as error:QMessageBox.warning(self,'Настройки',str(error))

    def save_profile(self):
        name,ok=QInputDialog.getText(self,'Свой профиль','Название:')
        if not ok or not name.strip() or name.strip() in PROFILES:return
        cfg=self.collect();name=name.strip()[:80]
        self.custom_profiles[name]={key:getattr(cfg,key) for key in ('softness','volume','noise_gate_db','pitch','auto_pitch','target_low','target_high')}
        path=user_dir()/'profiles.json';temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(self.custom_profiles,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
        if self.profile.findText(name)<0:self.profile.addItem(name)
        self.profile.setCurrentText(name)

    def open_recordings(self):
        folder=user_dir()/'recordings';folder.mkdir(exist_ok=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def toggle_monitor(self,value):
        if self.worker and self.worker.isRunning():
            if value:self.worker.monitor_enabled.set()
            else:self.worker.monitor_enabled.clear()

    def toggle_mute(self,value):
        if value:self.output_meter.setValue(0);self.input_meter.setValue(0)
        if self.worker and self.worker.isRunning():self.worker.request_mute(value)

    def primary_action(self,*_):
        if self.offline_job:
            self.offline_job.cancel.set();self.start.setEnabled(False);self.start.setText('Отмена…');return
        if self.cuda_available and self.compute.currentData()!='cpu':self.toggle_start()
        else:self.offline_convert()

    def toggle_start(self):
        if self.worker and self.worker.isRunning():self.worker.stop();self.start.setEnabled(False);self.start.setText('Остановка…');return
        if not self.cuda_available or self.compute.currentData()=='cpu':return
        if self.jobs:self.status_label.setText('Дождитесь завершения текущей операции');return
        try:
            cfg=self.collect();cfg.save();self.settings=cfg
            if self.monitor.isChecked() and not cfg.headphones:raise ValueError('Выберите наушники для прослушивания')
            if not cfg.output and not self.monitor.isChecked():raise ValueError('Выберите виртуальный выход или включите наушники')
            self.worker=AudioWorker(cfg,self.monitor.isChecked(),self.record.isChecked())
            if self.mute.isChecked():self.worker.request_mute(True)
            self.error_text='';self.worker.status.connect(self.status_label.setText);self.worker.metrics.connect(self.show_metrics)
            self.worker.failure.connect(self.show_failure);self.worker.active.connect(self.active_changed);self.worker.finished.connect(self.stopped)
            self.worker.start();self.update_availability()
        except Exception as error:QMessageBox.warning(self,'Запуск',str(error))

    def active_changed(self,active):
        self.tray.setIcon(icon(active));self.tray.setToolTip('AI Voice Changer · '+('микрофон включён' if active else 'микрофон выключен'))

    def stopped(self):
        self.input_meter.setValue(0);self.output_meter.setValue(0);self.update_availability()
        if self.error_text:self.status_label.setText(self.error_text)
        if self.quitting:self.quit_app()

    def show_failure(self,error):
        self.error_text='Выход отключён: '+error;QMessageBox.warning(self,'Преобразование остановлено',self.error_text)

    def show_metrics(self,data):
        self.input_meter.setValue(min(100,round(data.get('input_peak',0)*100)));self.output_meter.setValue(min(100,round(data.get('output_peak',0)*100)))
        if data.get('processing_paused'):self.timing.setText('Микрофон закрыт · выход заглушён')
        elif 'inference_median_ms' in data:
            self.timing.setText(f"Инференс {data['inference_median_ms']:.1f} мс · P95 {data['inference_p95_ms']:.1f} мс\nСквозная задержка: не измерена")
        self.diagnostic.setPlainText(json.dumps(self.hardware,ensure_ascii=False,indent=2)+'\n\n'+json.dumps(data,ensure_ascii=False,indent=2))

    def offline_convert(self,*_):
        if self.offline_job or (self.worker and self.worker.isRunning()):return
        source,_=QFileDialog.getOpenFileName(self,'Исходная запись','','Аудио (*.wav *.flac)')
        if not source:return
        suggested=Path(source).with_stem(Path(source).stem+'-female').with_suffix('.wav')
        output,_=QFileDialog.getSaveFileName(self,'Обработанный WAV',str(suggested),'WAV (*.wav)')
        if not output:return
        output=str(Path(output).with_suffix('.wav'))
        try:cfg=self.collect();cfg.save()
        except ValueError as error:QMessageBox.warning(self,'Настройки',str(error));return
        job=Job(None);self.offline_job=job;self.jobs.append(job)
        job.fn=lambda:convert_file(source,output,settings=cfg,progress=job.progress.emit,cancel=job.cancel)
        self.play_file.setEnabled(False);self.file_progress.setRange(0,0);self.update_availability()
        job.progress.connect(self.offline_status.setText);job.progress.connect(self.status_label.setText)
        def done(report):
            self.last_output=str(Path(output).resolve());self.play_file.setEnabled(True)
            self.offline_status.setText(f"Сохранено: {output}\nКонверсия {report['processing_seconds']:.1f} с + загрузка моделей {report['model_load_seconds']:.1f} с · {report['backend']}")
            self.status_label.setText('WAV сохранён · микрофон не использовался')
            self.diagnostic.setPlainText(json.dumps(report,ensure_ascii=False,indent=2))
            (user_dir()/'last-file-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        def failed(error):self.offline_status.setText(error);self.status_label.setText(error)
        def finished():
            self.offline_job=None;self.file_progress.setRange(0,1);self.file_progress.setValue(1 if self.play_file.isEnabled() else 0)
            self.finish_job(job);self.update_availability()
            if self.quitting:self.quit_app()
        job.done.connect(done);job.failed.connect(failed);job.finished.connect(finished);job.start()

    def setup_guide(self):
        box=QMessageBox(self);box.setWindowTitle('Виртуальный микрофон')
        box.setText('1. Установите VB-CABLE с официального сайта и перезагрузите Windows.\n'
                    '2. Обновите устройства в приложении.\n3. Выберите физический микрофон и CABLE Input.\n'
                    '4. В Discord / OBS выберите микрофон CABLE Output.\n5. На NVIDIA/CUDA запустите преобразование.\n\n'
                    'Драйвер не включён в сборку. Файловый режим работает без него.')
        site=box.addButton('Официальный сайт VB-CABLE',QMessageBox.ButtonRole.ActionRole);box.addButton(QMessageBox.StandardButton.Close);box.exec()
        if box.clickedButton()==site:QDesktopServices.openUrl(QUrl('https://vb-audio.com/Cable/'))

    def emergency_stop(self):
        self.mute.setChecked(True)
        if self.worker and self.worker.isRunning():self.worker.stop()

    def closeEvent(self,event):
        event.ignore()
        if self.worker and self.worker.isRunning() and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide();self.tray.showMessage('AI Voice Changer','Работает в трее. Ctrl+Alt+F10 отключает микрофон и выход.')
        else:self.quit_app()

    def quit_app(self):
        self.quitting=True
        if self.worker and self.worker.isRunning():self.worker.stop();return
        running=[job for job in self.jobs if job.isRunning()]
        if running:
            for job in running:job.cancel.set()
            self.status_label.setText('Отмена операции и завершение…');QTimer.singleShot(200,self.quit_app);return
        self.hotkeys.close();self.tray.hide();QApplication.instance().quit()


class MainWindow(AdvancedWindow):
    """One screen: quality, input, output, start. Legacy controls stay hidden."""
    def __init__(self):
        super().__init__()
        self.tabs.hide()
        self.setMinimumSize(520,400);self.resize(620,440)
        self.setWindowTitle('AI Voice Changer')
        layout=self.centralWidget().layout()
        for index in range(layout.count()):
            item=layout.itemAt(index)
            if item.widget():item.widget().hide()
        self.panel=QWidget();box=QVBoxLayout(self.panel);box.setSpacing(20)
        title=QLabel('AI Voice Changer');title.setStyleSheet('font-size:28px;font-weight:600;');box.addWidget(title)
        self.simple_form=QFormLayout();self.simple_form.setSpacing(16)
        self.mode.setItemText(0,'Быстрое');self.mode.setItemText(1,'Сбалансированное');self.mode.setItemText(2,'Высокое')
        self.simple_form.addRow('Качество',self.mode)
        self.simple_form.addRow('Вход · микрофон',self.mic);self.mic.show()
        self.simple_form.addRow('Выход · наушники',self.output);self.output.show()
        self.mic.refresh_callback=self.refresh_devices;self.output.refresh_callback=self.refresh_devices
        self.mode.show();box.addLayout(self.simple_form);self.start.show();box.addWidget(self.start)
        self.status_label.show();box.addWidget(self.status_label)
        self.file_progress.show();box.addWidget(self.file_progress)
        box.addStretch();layout.addWidget(self.panel)
        self.model_choice.setCurrentIndex(0);self.record.setChecked(False);self.monitor.setChecked(False)
        self.update_availability()
        if not self.cuda_available:self.status_label.setText('Готово · CPU: возможна заметная задержка')

    def refresh_devices(self):
        if self.worker and self.worker.isRunning():return
        old=[field.currentData() for field in (self.mic,self.output)]
        self.devices=self.native.devices();self.mic.clear();self.output.clear();self.headphones.clear()
        for device in self.devices:
            if device['flow']=='capture' and 'cable output' not in device['name'].lower():self.mic.addItem(device['name'],device['id'])
            if device['flow']=='render':self.output.addItem(device['name'],device['id'])
        for field,value in zip((self.mic,self.output),old):
            index=field.findData(value)
            if index>=0:field.setCurrentIndex(index)
        if not old[1]:
            for i,d in enumerate([d for d in self.devices if d['flow']=='render']):
                if virtual_output(d):self.output.setCurrentIndex(i);break

    def collect(self):
        mapping={'Быстрое':'Low Latency','Сбалансированное':'Balanced','Высокое':'High Quality'}
        cfg=Settings(microphone=self.mic.currentData() or '',output=self.output.currentData() or '',
            mode=mapping.get(self.mode.currentText(),self.mode.currentText()),threads=4,model='seed',backend='auto')
        return cfg.validate()

    def update_availability(self,*args):
        super().update_availability(*args)
        if hasattr(self,'panel'):
            busy=bool(self.offline_job) or bool(self.worker and self.worker.isRunning())
            self.mode.setEnabled(not busy)
            self.mic.setEnabled(not busy);self.output.setEnabled(not busy)
            if hasattr(self,'file_input'):
                self.file_input.setEnabled(not busy);self.file_output.setEnabled(not busy)
            if not busy:self.start.setText('Запустить')

    def primary_action(self,*args):
        self.toggle_start()

    def toggle_start(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop();self.start.setEnabled(False);self.start.setText('Остановка…');return
        if self.jobs:
            self.status_label.setText('Подготовка приложения…');return
        try:
            cfg=self.collect()
            if not cfg.microphone:raise ValueError('Выберите микрофон')
            if not cfg.output:raise ValueError('Выберите наушники или другое устройство вывода')
            cfg.save();self.settings=cfg
            self.worker=AudioWorker(cfg,False,False)
            self.error_text='';self.worker.status.connect(self.status_label.setText)
            self.worker.metrics.connect(self.show_metrics);self.worker.failure.connect(self.show_failure)
            self.worker.active.connect(self.active_changed);self.worker.finished.connect(self.stopped)
            self.worker.start();self.update_availability()
        except Exception as error:self.status_label.setText(str(error))

    def choose_input(self):
        path,_=QFileDialog.getOpenFileName(self,'Вход','','Аудио (*.wav *.flac)')
        if path:
            self.input_path=path;self.file_input.setText(Path(path).name)
            if not self.output_path:
                self.output_path=str(Path(path).with_stem(Path(path).stem+'-female').with_suffix('.wav'))
                self.file_output.setText(Path(self.output_path).name)

    def choose_output(self):
        path,_=QFileDialog.getSaveFileName(self,'Выход',self.output_path,'WAV (*.wav)')
        if path:
            self.output_path=str(Path(path).with_suffix('.wav'));self.file_output.setText(Path(self.output_path).name)

    def offline_convert(self,*args):
        if not hasattr(self,'input_path'):return super().offline_convert(*args)
        if not self.input_path:self.status_label.setText('Выберите входную запись');return
        if not self.output_path:self.status_label.setText('Выберите выходной WAV');return
        if Path(self.output_path).exists():
            if QMessageBox.question(self,'Выход','Заменить существующий WAV?')!=QMessageBox.StandardButton.Yes:return
        # Reuse the production worker while bypassing redundant picker dialogs.
        original_open,original_save=QFileDialog.getOpenFileName,QFileDialog.getSaveFileName
        try:
            QFileDialog.getOpenFileName=lambda *a,**k:(self.input_path,'')
            QFileDialog.getSaveFileName=lambda *a,**k:(self.output_path,'')
            return super().offline_convert(*args)
        finally:
            QFileDialog.getOpenFileName=original_open;QFileDialog.getSaveFileName=original_save

    def check_updates(self):
        if self.jobs or (self.worker and self.worker.isRunning()):
            self.status_label.setText('Сначала остановите преобразование');return
        from .updates import prepare_update
        from . import __version__
        job=Job(lambda:prepare_update(__version__));self.jobs.append(job)
        self.status_label.setText('Проверяю обновления…')
        job.done.connect(self.status_label.setText)
        job.failed.connect(lambda error:self.status_label.setText('Не удалось обновить: '+error))
        job.finished.connect(lambda:self.finish_job(job));job.start()
