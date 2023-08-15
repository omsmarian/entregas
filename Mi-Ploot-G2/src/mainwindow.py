# PyQt5 modules
from math import inf
from PyQt5.QtWidgets import QMainWindow, QListWidgetItem, QColorDialog, QFileDialog, QDialog, QStyle
from PyQt5.QtCore import Qt
from matplotlib.widgets import Lasso
from matplotlib.collections import RegularPolyCollection
from matplotlib import colors as mcolors, path

# Project modules
from src.ui.mainwindow import Ui_MainWindow
from src.package.Dataset import Dataset
import src.package.Filter as Filter
from src.package.Filter import AnalogFilter
from src.widgets.exprwidget import MplCanvas
from src.widgets.tf_dialog import TFDialog
from src.widgets.case_window import CaseDialog
from src.widgets.zp_window import ZPWindow
from src.widgets.response_dialog import ResponseDialog
from src.widgets.prompt_dialog import PromptDialog

from scipy.signal import savgol_filter
import scipy.signal as signal
from scipy.interpolate import splrep, splev, splprep
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from mplcursors import HoverMode, cursor, Selection
from matplotlib.patches import Rectangle

import colorsys
import numpy as np
import random
from pyparsing.exceptions import ParseSyntaxException

import pickle

MARKER_STYLES = { 'None': '', 'Point': '.',  'Pixel': ',',  'Circle': 'o',  'Triangle down': 'v',  'Triangle up': '^',  'Triangle left': '<',  'Triangle right': '>',  'Tri down': '1',  'Tri up': '2',  'Tri left': '3',  'Tri right': '4',  'Octagon': '8',  'Square': 's',  'Pentagon': 'p',  'Plus (filled)': 'P',  'Star': '*',  'Hexagon': 'h',  'Hexagon alt.': 'H',  'Plus': '+',  'x': 'x',  'x (filled)': 'X',  'Diamond': 'D',  'Diamond (thin)': 'd',  'Vline': '|',  'Hline': '_' }
LINE_STYLES = { 'None': '', 'Solid': '-', 'Dashed': '--', 'Dash-dot': '-.', 'Dotted': ':' }

POLE_COLOR = '#FF0000'
POLE_SEL_COLOR = '#00FF00'
ZERO_COLOR = '#0000FF'
ZERO_SEL_COLOR = '#00FF00'

TEMPLATE_FACE_COLOR = '#ffcccb'
TEMPLATE_EDGE_COLOR = '#ef9a9a'
ADD_TEMPLATE_FACE_COLOR = '#c8e6c9'
ADD_TEMPLATE_EDGE_COLOR = '#a5d6a7'

SHOW_PZ_IN_HZ = True
PZ_XLABEL = f'$\sigma$ [1/s]' if SHOW_PZ_IN_HZ else '$\sigma$ ($rad/s$)'
PZ_YLABEL = f'$jf$ [Hz]' if SHOW_PZ_IN_HZ else '$j\omega$ ($rad/s$)'
F_TO_W = 2*np.pi
W_TO_F = 1/F_TO_W
SING_B_TO_F = W_TO_F if SHOW_PZ_IN_HZ else 1
SING_F_TO_B = F_TO_W if SHOW_PZ_IN_HZ else 1

def stage_to_str(stage):
    stage_str = 'Z={'
    for z in stage.z:
        stage_str += str(z)
        stage_str += ', '
    stage_str += '} , P={'
    for p in stage.p:
        stage_str += str(p)
        stage_str += ', '
    stage_str += '} , K='
    stage_str+= str(stage.k)
    return stage_str




class LassoManager(object):
    def __init__(self, canvas, data, color, flags, location):
        self.canvas = canvas
        self.axes = canvas.ax
        self.data = data
        self.loc = location
        self.selected_indices = []
        self.color = mcolors.to_rgba(color)
        self.line_colors = [self.get_opposite_color(self.color,i) for i in range(4)]
        self.Nxy = len(data[0])
        self.flags = flags

        self.xys = [(data[0][i], data[1][i]) for i in range(len(data[0]))]
        
        self.processed_data_line = None  # Line for processed data plot
        self.first_last_line = None  # Line for first-last points connection
        self.first_last_max_line = None  # Max line
        self.first_last_min_line = None  # Min line
        self.average_line = None
        self.rms_line = None
        
        self.cid = self.canvas.mpl_connect('button_press_event', self.onpress)

    def callback(self, verts):
        p = path.Path(verts)
        ind = p.contains_points(self.xys)
        self.selected_indices = [i for i in range(len(self.xys)) if ind[i]]
        
        # Clear previous processed data lines
        if self.first_last_line:
            self.remove_label(self.first_last_line)
            self.first_last_line.remove()
            self.first_last_line = None
            
        if self.first_last_max_line:
            self.remove_label(self.first_last_max_line)
            self.first_last_max_line.remove()
            self.first_last_max_line = None
            
        if self.first_last_min_line:
            self.remove_label(self.first_last_min_line)
            self.first_last_min_line.remove()
            self.first_last_min_line = None
        
        if self.average_line:
            self.remove_label(self.average_line)
            self.average_line.remove()
            self.average_line = None

        if self.rms_line:
            self.remove_label(self.rms_line)
            self.rms_line.remove()
            self.rms_line = None
            
        self.process_selected_data(self.selected_indices)
        self.canvas.draw_idle()
        self.canvas.widgetlock.release(self.lasso)
        del self.lasso

    def process_selected_data(self, indices):
        if not indices:
            return
        
        selected_y = [self.data[1][i] for i in indices]
        selected_x = [self.data[0][i] for i in indices]

        # 1. Valor máximo y mínimo en "y"
        self.y_max = max(selected_y)
        self.y_min = min(selected_y)
        # 2. Pendiente entre el primer y último dato
        self.slope = (selected_y[-1] - selected_y[0]) / (selected_x[-1] - selected_x[0])
        
        # 3. Promedio de los valores "y"
        self.y_avg = sum(selected_y) / len(selected_y)

        # 4. Valor RMS de la señal 
        self.y_rms = np.sqrt(np.mean(np.array(selected_y)**2))
        
        # Update the plot with processed data
        self.plot_processed_data(selected_x, selected_y)
    
    def plot_processed_data(self, x, y):
        # Plot the processed data
        if self.flags[0]:
            self.first_last_max_line = self.axes.axhline(self.y_max, color = self.color, 
                                                         linestyle = 'dashed', label =f"Maximo = {self.y_max:.2f}")
        if self.flags[1]:
            self.first_last_min_line = self.axes.axhline(self.y_min, color = self.color,
                                                         linestyle = 'dashed', label =f"Minimo = {self.y_min:.2f}")
        
        
        # Plot the line connecting first and last points
        if self.flags[2]:
            x_first_last = [x[0], x[-1]]
            y_first_last = [y[0], y[-1]]
            self.first_last_line = self.axes.plot(x_first_last, y_first_last, color=self.line_colors[2],
                                                  linestyle='--', label=f"Pendiente = {self.slope:.2f}")[0]
        
        #Plot the average line
        if self.flags[3]:
            self.average_line = self.axes.axhline(self.y_avg, color = self.line_colors[0],
                                                  linestyle='--', label=f"Promedio = {self.y_avg:.2f}")
        
        #Plot the RMS line
        if self.flags[4]:
            self.rms_line = self.axes.axhline(self.y_rms, color = self.line_colors[1],linestyle='--',label=f"RMS = {self.y_rms:.2f}")
        
        if self.loc != 11:
            self.axes.legend(loc = self.loc)
        self.canvas.draw()
        

    def remove_label(self, line):
        handles, labels = self.axes.get_legend_handles_labels()
        index = handles.index(line)
        handles.pop(index)
        labels.pop(index)
        self.axes.legend(handles, labels)
        plt.draw()

    def onpress(self, event):
        #if self.canvas.widgetlock.locked():
         #   return
        if event.inaxes is None:
            return
        self.lasso = Lasso(event.inaxes,
                           (event.xdata, event.ydata),
                           self.callback)
        # acquire a lock on the widget drawing
        #self.canvas.widgetlock(self.lasso)
    
    def get_opposite_color(self, base_color, index):
        base_hsv = mcolors.rgb_to_hsv(base_color[:3])  # Convertir RGB a HSV
        
        hue = (base_hsv[0] + index * 0.2) % 1.0  # Cambiar el tono en intervalos de 0.2
        lightness = (0.4 + index * 0.2) % 1.0  # Cambiar la luminosidad en intervalos de 0.2
        rgb = colorsys.hsv_to_rgb(hue, 1.0, lightness)
        rgba = (rgb[0], rgb[1], rgb[2], base_color[3])  # Mantener la opacidad del color base
        
        return rgba


class MainWindow(QMainWindow, Ui_MainWindow):

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setupUi(self)
        self.droppedFiles = []
        self.datasets = []
        self.datalines = []
        self.flags=[False,False,False,False,False]
        # self.stage_datasets = [] capaz mas adelante lo ponga para serializar también las etapas, pero creo que para ahora es mucho
        self.selected_dataset_widget = {}
        self.selected_dataline_widget = {}
        self.selected_dataset_data = {}
        self.selected_dataline_data = {}
        self.zpWindow = type('ZPWindow', (), {})()
        self.import_file_btn.clicked.connect(self.importFiles)
        
        self.Maximo.stateChanged.connect(lambda:self.getFlags(0))
        self.Minimo.stateChanged.connect(lambda:self.getFlags(1))
        self.Promedio.stateChanged.connect(lambda:self.getFlags(3))
        self.Pendiente.stateChanged.connect(lambda:self.getFlags(2))
        self.Rms.stateChanged.connect(lambda:self.getFlags(4))
        
        self.dataset_list.currentItemChanged.connect(self.populateSelectedDatasetDetails)
        self.ds_title_edit.textEdited.connect(self.updateSelectedDatasetName)
        self.ds_addline_btn.clicked.connect(self.addDataline)
        self.ds_remove_btn.clicked.connect(self.removeSelectedDataset)
        self.ds_poleszeros_btn.clicked.connect(self.showZPWindow)

        self.dataline_list.currentItemChanged.connect(self.populateSelectedDatalineDetails)
        self.dl_name_edit.textEdited.connect(self.updateSelectedDataline)
        self.dl_render_cb.activated.connect(self.updateSelectedDataline)
        self.dl_transform_cb.activated.connect(self.updateSelectedDataline)
        self.dl_xdata_cb.activated.connect(self.updateSelectedDataline)
        self.dl_xscale_sb.valueChanged.connect(self.updateSelectedDataline)
        self.dl_xoffset_sb.valueChanged.connect(self.updateSelectedDataline)
        self.dl_ydata_cb.activated.connect(self.updateSelectedDataline)
        self.dl_yscale_sb.valueChanged.connect(self.updateSelectedDataline)
        self.dl_yoffset_sb.valueChanged.connect(self.updateSelectedDataline)
        self.dl_color_edit.textEdited.connect(self.updateSelectedDataline)
        self.dl_style_cb.activated.connect(self.updateSelectedDataline)
        self.dl_linewidth_sb.valueChanged.connect(self.updateSelectedDataline)
        self.dl_marker_cb.activated.connect(self.updateSelectedDataline)
        self.dl_markersize_sb.valueChanged.connect(self.updateSelectedDataline)
        self.dl_remove_btn.clicked.connect(self.removeSelectedDataline)
        self.dl_savgol_wlen.valueChanged.connect(self.updateSelectedDataline)
        self.dl_savgol_ord.valueChanged.connect(self.updateSelectedDataline)

        self.dl_color_pickerbtn.clicked.connect(self.openColorPicker)

        self.respd = ResponseDialog()
        self.resp_btn.clicked.connect(self.openResponseDialog)
        self.respd.accepted.connect(self.resolveResponseDialog)

        self.tfd = TFDialog()
        self.function_btn.clicked.connect(self.openTFDialog)
        self.tfd.accepted.connect(self.resolveTFDialog)

        self.csd = CaseDialog()
        self.ds_caseadd_btn.clicked.connect(self.openCaseDialog)
        self.csd.accepted.connect(self.resolveCSDialog)

        self.pmptd = PromptDialog()
        
        self.plt_labelsize_sb.valueChanged.connect(self.updatePlots)
        self.plt_legendsize_sb.valueChanged.connect(self.updatePlots)
        self.plt_ticksize_sb.valueChanged.connect(self.updatePlots)
        self.plt_titlesize_sb.valueChanged.connect(self.updatePlots)
        self.plt_autoscale.clicked.connect(self.autoscalePlots)
        self.plt_legendpos.activated.connect(self.updatePlots)
        self.plt_grid.stateChanged.connect(self.updatePlots)
        self.tabbing_plots.currentChanged.connect(self.updatePlots)
        
        self.plots_canvases = [
            [ self.plot_1 ],
            [ self.plot_2_1, self.plot_2_2 ],
            [ self.plot_3 ],
            [ self.plot_4_1, self.plot_4_2 ],
            [ self.plot_5 ],
        ]

        self.new_filter_btn.clicked.connect(self.addFilter)
        self.chg_filter_btn.clicked.connect(self.changeSelectedFilter)
        self.tipo_box.currentIndexChanged.connect(self.updateFilterParametersAvailable)
        self.define_with_box.currentIndexChanged.connect(self.updateFilterParametersAvailable)
        self.updateFilterParametersAvailable()

        self.new_stage_btn.clicked.connect(self.addFilterStage)
        self.remove_stage_btn.clicked.connect(self.removeFilterStage)

        self.actionLoad_2.triggered.connect(self.loadFile)
        self.actionSave_2.triggered.connect(self.saveFile)

        self.stageCursorZer = {}
        self.stageCursorPol = {}

        self.poles_list.itemSelectionChanged.connect(self.stage_sel_changed)
        self.zeros_list.itemSelectionChanged.connect(self.stage_sel_changed)
        self.stages_list.itemSelectionChanged.connect(self.updateStagePlots)

        self.filters = []
        self.selfil_cb.currentIndexChanged.connect(self.populateSelectedFilterDetails)
        self.stages_selfil_cb.currentIndexChanged.connect(self.populateSelectedFilterDetails)
        self.symmetrize_btn.clicked.connect(self.makeFilterTemplateSymmetric)

        self.sswapup_btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarShadeButton))
        self.sswapdown_btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarUnshadeButton))
        self.sswapup_btn.clicked.connect(self.swapStagesUpwards)
        self.sswapdown_btn.clicked.connect(self.swapStagesDownwards)
        self.autoselectstagessp_btn.clicked.connect(self.orderStagesBySos)

        self.prevFilterType = Filter.LOW_PASS
        self.compareapprox_cb.setCurrentIndexes([])
        self.lman = {}

    def addDataset(self, ds):
        qlwt = QListWidgetItem()
        qlwt.setData(Qt.UserRole, ds)
        qlwt.setText(ds.title)
        self.dataset_list.addItem(qlwt)
        self.datasets.append(ds)
        self.datalines.append([])
        self.dataset_list.setCurrentRow(self.dataset_list.count() - 1)

    def removeDataset(self, i):
        #Saco los datalines
        first_dataline_index = 0
        last_dataline_index = len(self.datalines[0])
        for x in range(self.dataset_list.count()):
            if(x == 0):
                first_dataline_index = 0
            else:    
                first_dataline_index += len(self.datalines[x - 1])
            if(x == i):
                break
        last_dataline_index = first_dataline_index + len(self.datalines[i])

        for x in range(first_dataline_index, last_dataline_index):
            self.dataline_list.takeItem(first_dataline_index)
        self.datalines.pop(i)

        ds = self.dataset_list.item(i).data(Qt.UserRole)
        if(ds.type == 'filter'):
            fi = self.filters.index(ds)
            self.filters.pop(fi)
            self.selfil_cb.removeItem(fi)
            self.stages_selfil_cb.removeItem(fi)
            if(self.selfil_cb.count() == 0):
                self.chg_filter_btn.setEnabled(False)
        self.dataset_list.takeItem(i)
        self.updatePlots()

    def addDataline(self):
        if(not self.selected_dataset_data):
            return
        dl = self.selected_dataset_data.create_dataline()
        qlwt = QListWidgetItem()
        qlwt.setData(Qt.UserRole, dl)
        qlwt.setText(dl.name)
        dli = 0
        for x in range(self.dataset_list.count()):
            ds = self.dataset_list.item(x).data(Qt.UserRole)
            dli += len(self.datalines[x])
            if(ds.origin == self.selected_dataset_data.origin):
                break
        self.dataline_list.insertItem(dli, qlwt)
        self.dataline_list.setCurrentRow(dli)
        self.datalines[self.dataset_list.currentRow()].append(dl)
        self.updateSelectedDataline()
        self.updatePlots()

    def removeDataline(self, i):        
        try:
            dsi, dli = self.getInternalDataIndexes(i)
            del self.datalines[dsi][dli]
            self.dataline_list.takeItem(i).data(Qt.UserRole)
            del self.dataset_list.item(dsi).data(Qt.UserRole).datalines[dli]
            if(self.dataline_list.currentRow() == -1):
                self.dataline_list.setCurrentRow(self.dataline_list.count() - 1)
        except AttributeError:
            pass
        self.updatePlots()
    
    def removeSelectedDataline(self, event):
        selected_row = self.dataline_list.currentRow()
        self.removeDataline(selected_row)

    def removeSelectedDataset(self, event):
        selected_row = self.dataset_list.currentRow()
        self.removeDataset(selected_row)

    def getInternalDataIndexes(self, datalineRow):
        i = self.dataline_list.currentRow()
        for x in range(self.dataset_list.count()):
            ds = self.dataset_list.item(x).data(Qt.UserRole)
            if(i >= len(self.datalines[x])):
                i = i - len(self.datalines[x])
            else:
                return (x, i)
        return (x, i)

    def dragEnterEvent(self, event):
        if(event.mimeData().hasUrls()):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        self.statusbar.showMessage('Loading files')
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        self.processFiles(files)

    def importFiles(self):
        options = QFileDialog.Options()
        # options |= QFileDialog.DontUseNativeDialog
        files, _ = QFileDialog.getOpenFileNames(self,"Select files", "","All Files (*);;CSV files (*.csv);;SPICE output files (*.raw)", options=options)
        self.processFiles(files)

    def processFiles(self, filenamearray):
        for f in filenamearray:
            try:
                ds = Dataset(filepath=f)
                dataset_items_origin = [
                    self.dataset_list.item(x).data(Qt.UserRole).origin
                    for x in range(self.dataset_list.count())
                ]
                if(ds.origin not in dataset_items_origin):
                    self.droppedFiles.append(ds.origin)
                    self.addDataset(ds)
            except(ValueError):
                print('Wrong file config')
        self.statusbar.clearMessage()

    def openTFDialog(self):
        self.tfd.open()
        self.tfd.tf_title.setFocus()

    def resolveTFDialog(self):
        if not self.tfd.validateTF():
            return
        ds = Dataset(filepath='', origin=self.tfd.tf, title=self.tfd.getTFTitle())
        self.addDataset(ds)

    def openResponseDialog(self):
        self.respd.open()
        self.respd.input_txt.setFocus()

    def resolveResponseDialog(self):
        if not(self.respd.validateResponse()):
            return

        t = self.respd.getTimeDomain()
        expression = self.respd.getResponseExpression()
        title = self.respd.getResponseTitle()
        time_title = title + "_timebase"
        ans_title = title + "_ans"
        
        if expression == 'step':
            x = np.heaviside(t, 0.5)
            _, response = signal.step(self.selected_dataset_data.tf.tf_object, T=t)
        elif expression == 'delta':
            delta = lambda t, eps: (1 / (np.sqrt(np.pi) *eps)) * np.exp(-(t/eps)**2) #para plotear la delta
            x = delta(t, (t[1] - t[0]))
            _, response = signal.delta(self.selected_dataset_data.tf.tf_object, T=t)
        else:
            x = eval(expression)
            response = signal.lsim(self.selected_dataset_data.tf.tf_object , U = x , T = t)[1]
        
        self.selected_dataset_data.data[0][time_title] = t
        self.selected_dataset_data.data[0][title] = x
        self.selected_dataset_data.data[0][ans_title] = response

        self.selected_dataset_data.fields.append(time_title)
        self.selected_dataset_data.fields.append(title)
        self.selected_dataset_data.fields.append(ans_title)
        
        self.updateSelectedDataset()
        self.updateSelectedDataline()

    def buildFilterFromParams(self):
        if(self.prevFilterType != self.tipo_box.currentIndex()):
            self.compareapprox_cb.setCurrentIndexes([])
        self.prevFilterType = self.tipo_box.currentIndex()
        if self.tipo_box.currentIndex() in [Filter.BAND_PASS, Filter.BAND_REJECT]:
            wa = [F_TO_W * self.fa_min_box.value(), F_TO_W * self.fa_max_box.value()]
            wp = [F_TO_W * self.fp_min_box.value(), F_TO_W * self.fp_max_box.value()]
        else:
            wa = F_TO_W * self.fa_box.value()
            wp = F_TO_W * self.fp_box.value()
            
        params = {
            "name": self.filtername_box.text(),
            "filter_type": self.tipo_box.currentIndex(),
            "approx_type": self.aprox_box.currentIndex(),
            "helper_approx": self.compareapprox_cb.currentIndexes(),
            "helper_N": self.comp_N_box.value(),
            "is_helper": False,
            "define_with": self.define_with_box.currentIndex(),
            "N_min": self.N_min_box.value(),
            "N_max": self.N_max_box.value(),
            "gain": self.gain_box.value(),
            "denorm": self.denorm_box.value(),
            "aa_dB": self.aa_box.value(),
            "ap_dB": self.ap_box.value(),
            "wa": wa,
            "wp": wp,
            "w0": F_TO_W * self.f0_box.value(),
            "bw": [F_TO_W * self.bw_min_box.value(), F_TO_W * self.bw_max_box.value()],
            "gamma": self.tol_box.value(),
            "tau0": self.tau0_box.value(),
            "wrg": F_TO_W * self.frg_box.value(),
        }
        return AnalogFilter(**params)
    
    def addFilter(self):
        newFilter = self.buildFilterFromParams()
        valid, msg = newFilter.validate()
        if not valid:
            self.pmptd.setErrorMsg(msg)
            self.pmptd.open()
            self.pmptd.setFocus()
            return
        ds = Dataset(filepath='', origin=newFilter, title=self.filtername_box.text())
        self.filters.append(ds)
        self.selfil_cb.blockSignals(True)
        self.stages_selfil_cb.blockSignals(True)
        self.selfil_cb.addItem(ds.title, ds)
        self.stages_selfil_cb.addItem(ds.title, ds)
        self.selfil_cb.blockSignals(False)
        self.stages_selfil_cb.blockSignals(False)
        self.chg_filter_btn.setEnabled(True)
        self.addDataset(ds)
    
    def makeFilterTemplateSymmetric(self):
        fa = [self.fa_min_box.value(), self.fa_max_box.value()]
        fp = [self.fp_min_box.value(), self.fp_max_box.value()]
        f0 = 0
        bw = [0, 0]
        if(self.tipo_box.currentIndex() == Filter.BAND_PASS):
            f0 = np.sqrt(fp[0] * fp[1])
            bw[0] = fp[1] - fp[0]
            if(fa[0] * fa[1] != f0**2):
                famincalc = f0**2 / fa[1]
                famaxcalc = f0**2 / fa[0]
                if(famincalc > fa[0]):
                    fa[0] = famincalc
                elif(famaxcalc < fa[1]):
                    fa[1] = famaxcalc
            bw[1] = fa[1] - fa[0]

        elif(self.tipo_box.currentIndex() == Filter.BAND_REJECT):
            f0 = np.sqrt(fa[0] * fa[1])
            bw[0] = fa[1] - fa[0]
            if(fp[0] * fp[1] != f0**2):
                fpmincalc = f0**2 / fp[1]
                fpmaxcalc = f0**2 / fp[0]
                if(fpmincalc > fp[0]):
                    fp[0] = fpmincalc
                elif(fpmaxcalc < fp[1]):
                    fp[1] = fpmaxcalc    
            bw[1] = fp[1] - fp[0]

        self.fa_min_box.setValue(fa[0])
        self.fa_max_box.setValue(fa[1])
        self.fp_min_box.setValue(fp[0])
        self.fp_max_box.setValue(fp[1])
        self.f0_box.setValue(f0)
        self.bw_min_box.setValue(bw[0])
        self.bw_max_box.setValue(bw[1])

    def changeSelectedFilter(self):
        newFilter = self.buildFilterFromParams()
        valid, msg = newFilter.validate()
        if not valid:
            self.pmptd.setErrorMsg(msg)
            self.pmptd.setFocus()
            return
        temp_datalines = self.selected_dataset_data.datalines
        ds = Dataset('', self.filtername_box.text(), newFilter)
        ds.datalines = temp_datalines
        ds.title = self.filtername_box.text()
        self.selected_dataset_widget.setText(self.filtername_box.text())
        self.selfil_cb.setItemText(self.selfil_cb.currentIndex(), ds.title)
        self.stages_selfil_cb.setItemText(self.selfil_cb.currentIndex(), ds.title)
        self.selected_dataset_widget.setData(Qt.UserRole, ds)
        self.filters[self.selfil_cb.currentIndex()] = ds
        self.populateSelectedDatasetDetails(self.selected_dataset_widget, None)

    def updateFilterParametersAvailable(self):
        if self.tipo_box.currentIndex() == Filter.LOW_PASS or self.tipo_box.currentIndex() == Filter.HIGH_PASS:
            for i in range(Filter.LEGENDRE + 1):
                self.aprox_box.model().item(i).setEnabled(True)
                self.compareapprox_cb.model().item(i).setEnabled(True)
            for i in range(Filter.BESSEL, Filter.GAUSS + 1):
                self.aprox_box.model().item(i).setEnabled(False)
                self.compareapprox_cb.model().item(i).setEnabled(False)
            if not self.aprox_box.model().item(self.aprox_box.currentIndex()).isEnabled():
                self.aprox_box.setCurrentIndex(Filter.BUTTERWORTH)
                self.compareapprox_cb.setCurrentIndex(Filter.BUTTERWORTH)
            self.define_with_box.setVisible(False)
            self.label_definewith.setVisible(False)
            self.ap_box.setVisible(True)
            self.label_ap.setVisible(True)
            self.aa_box.setVisible(True)
            self.label_aa.setVisible(True)
            self.fp_box.setVisible(True)
            self.label_fp.setVisible(True)
            self.fa_box.setVisible(True)
            self.label_fa.setVisible(True)
            self.fa_min_box.setVisible(False)
            self.symmetrize_btn.setVisible(False)
            self.label_famin.setVisible(False)
            self.fa_max_box.setVisible(False)
            self.label_famax.setVisible(False)
            self.fp_min_box.setVisible(False)
            self.label_fpmin.setVisible(False)
            self.fp_max_box.setVisible(False)
            self.label_fpmax.setVisible(False)
            self.f0_box.setVisible(False)
            self.label_f0.setVisible(False)
            self.bw_min_box.setVisible(False)
            self.label_bwmin.setVisible(False)
            self.bw_max_box.setVisible(False)
            self.label_bwmax.setVisible(False)
            self.tau0_box.setVisible(False)
            self.label_tau0.setVisible(False)
            self.frg_box.setVisible(False)
            self.label_fRG.setVisible(False)
            self.tol_box.setVisible(False)
            self.label_tolerance.setVisible(False)

        elif self.tipo_box.currentIndex() == Filter.BAND_PASS or self.tipo_box.currentIndex() == Filter.BAND_REJECT:
            for i in range(Filter.LEGENDRE + 1):
                self.aprox_box.model().item(i).setEnabled(True)
                self.compareapprox_cb.model().item(i).setEnabled(True)
            for i in range(Filter.BESSEL, Filter.GAUSS + 1):
                self.aprox_box.model().item(i).setEnabled(False)
                self.compareapprox_cb.model().item(i).setEnabled(False)
            if not self.aprox_box.model().item(self.aprox_box.currentIndex()).isEnabled():
                self.aprox_box.setCurrentIndex(Filter.BUTTERWORTH)
                self.compareapprox_cb.setCurrentIndex(Filter.BUTTERWORTH)
            self.define_with_box.setVisible(True)
            self.label_definewith.setVisible(True)
            self.ap_box.setVisible(True)
            self.label_ap.setVisible(True)
            self.aa_box.setVisible(True)
            self.label_aa.setVisible(True)
            self.fp_box.setVisible(False)
            self.label_fp.setVisible(False)
            self.fa_box.setVisible(False)
            self.label_fa.setVisible(False)
            self.tau0_box.setVisible(False)
            self.label_tau0.setVisible(False)
            self.frg_box.setVisible(False)
            self.label_fRG.setVisible(False)
            self.tol_box.setVisible(False)
            self.label_tolerance.setVisible(False)

            if self.define_with_box.currentIndex() == Filter.TEMPLATE_FREQS:
                self.fa_min_box.setVisible(True)
                self.label_famin.setVisible(True)
                self.fa_max_box.setVisible(True)
                self.label_famax.setVisible(True)
                self.fp_min_box.setVisible(True)
                self.label_fpmin.setVisible(True)
                self.fp_max_box.setVisible(True)
                self.label_fpmax.setVisible(True)
                self.f0_box.setVisible(False)
                self.label_f0.setVisible(False)
                self.bw_min_box.setVisible(False)
                self.label_bwmin.setVisible(False)
                self.bw_max_box.setVisible(False)
                self.label_bwmax.setVisible(False)
                self.symmetrize_btn.setVisible(True)

            if self.define_with_box.currentIndex() == Filter.F0_BW:
                self.fa_min_box.setVisible(False)
                self.label_famin.setVisible(False)
                self.fa_max_box.setVisible(False)
                self.label_famax.setVisible(False)
                self.fp_min_box.setVisible(False)
                self.label_fpmin.setVisible(False)
                self.fp_max_box.setVisible(False)
                self.label_fpmax.setVisible(False)
                self.f0_box.setVisible(True)
                self.label_f0.setVisible(True)
                self.bw_min_box.setVisible(True)
                self.label_bwmin.setVisible(True)
                self.bw_max_box.setVisible(True)
                self.label_bwmax.setVisible(True)
                self.symmetrize_btn.setVisible(False)
        
        elif self.tipo_box.currentIndex() == Filter.GROUP_DELAY:
            for i in range(Filter.LEGENDRE + 1):
                self.aprox_box.model().item(i).setEnabled(False)
                self.compareapprox_cb.model().item(i).setEnabled(False)
            for i in range(Filter.BESSEL, Filter.GAUSS + 1):
                self.aprox_box.model().item(i).setEnabled(True)
                self.compareapprox_cb.model().item(i).setEnabled(True)
            if not self.aprox_box.model().item(self.aprox_box.currentIndex()).isEnabled():
                self.aprox_box.setCurrentIndex(Filter.BESSEL)
                self.compareapprox_cb.setCurrentIndex(Filter.BESSEL)
            
            self.define_with_box.setVisible(False)
            self.label_definewith.setVisible(False)
            self.ap_box.setVisible(False)
            self.label_ap.setVisible(False)
            self.aa_box.setVisible(False)
            self.label_aa.setVisible(False)
            self.fp_box.setVisible(False)
            self.label_fp.setVisible(False)
            self.fa_box.setVisible(False)
            self.label_fa.setVisible(False)
            self.fa_min_box.setVisible(False)
            self.label_famin.setVisible(False)
            self.fa_max_box.setVisible(False)
            self.label_famax.setVisible(False)
            self.fp_min_box.setVisible(False)
            self.label_fpmin.setVisible(False)
            self.fp_max_box.setVisible(False)
            self.label_fpmax.setVisible(False)
            self.f0_box.setVisible(False)
            self.label_f0.setVisible(False)
            self.bw_min_box.setVisible(False)
            self.label_bwmin.setVisible(False)
            self.bw_max_box.setVisible(False)
            self.label_bwmax.setVisible(False)
            self.tau0_box.setVisible(True)
            self.label_tau0.setVisible(True)
            self.frg_box.setVisible(True)
            self.label_fRG.setVisible(True)
            self.tol_box.setVisible(True)
            self.label_tolerance.setVisible(True)
            self.symmetrize_btn.setVisible(False)

    def condition_canvas(self, canvas, xlabel, ylabel, xscale='linear', yscale='linear', grid=True):
        canvas.ax.clear()
        canvas.ax.grid(grid, which="both", linestyle=':')
        canvas.ax.set_xlabel(xlabel)
        canvas.ax.set_ylabel(ylabel)
        canvas.ax.set_xscale(xscale)
        canvas.ax.set_yscale(yscale)
        canvas.ax.xaxis.label.set_size(self.plt_labelsize_sb.value())
        canvas.ax.yaxis.label.set_size(self.plt_labelsize_sb.value())
        for label in (canvas.ax.get_xticklabels() + canvas.ax.get_yticklabels()):
            label.set_fontsize(self.plt_ticksize_sb.value())

    def updateFilterPlots(self):
        pass

    def updateFilterStages(self):
        pass

    def stage_sel_changed(self):
        pass
                
    def updateSelectedPolesFromPlot(self, s):
        pass

    def updateSelectedZerosFromPlot(self, s):
        pass

    def addFilterStage(self):
        pass

    def swapStagesUpwards(self):
        pass

    def swapStagesDownwards(self):
        pass

    def orderStagesBySos(self):
        pass

    def removeFilterStage(self):
        pass

    def formatPoleAnnotation(self, sel):
        sel.annotation.set_text('Pole {:d}\n{:.2f}+j{:.2f}\nQ={:.2f}'.format(sel.index, sel.target[0], sel.target[1], self.calcQ(sel.target)))

    def formatZeroAnnotation(self, sel):
        if(True or sel.target[0] == 0 and sel.target[1] == 0):
            sel.annotation.set_text('Zero {:d}\n{:.2f}+j{:.2f}'.format(sel.index, sel.target[0], sel.target[1]))
        else:
            sel.annotation.set_text('Zero {:d}\n{:.2f}+j{:.2f}\nQ={:.2f}'.format(sel.index, sel.target[0], sel.target[1], self.calcQ(sel.target)))

    def calcQ(self, singRe, singIm):
        return self.calcQ(singRe + singIm*1j)

    def calcQ(self, sing):
        if(isinstance(sing, (list, tuple, np.ndarray))):
            sing = sing[0] + sing[1]*1j
        if(sing.real == 0):
            return inf
        elif(sing.real > 0):
            return -1
        else:
            return np.abs(sing)/(- 2 * sing.real)

    def updateStagePlots(self):
        pass

    def clearCanvas(self, canvas):
        canvas.ax.clear()
        canvas.ax.grid(True, which="both", linestyle=':')

    def openCaseDialog(self):
        self.csd.open()
        self.csd.populate(ds = self.selected_dataset_data)
        # self.tfd.tf_title.setFocus()

    def resolveCSDialog(self):
        first_case = int(self.csd.case_first_cb.currentIndex())
        last_case = int(self.csd.case_last_cb.currentIndex())
        casenum = len(self.selected_dataset_data.data)
        dli = 0
        for x in range(self.dataset_list.count()):
            ds = self.dataset_list.item(x).data(Qt.UserRole)
            dli = dli + len(self.datalines[x])
            if(ds.origin == self.selected_dataset_data.origin):
                break
        color_iter = 0
        for case in range(first_case, min(last_case + 1, casenum)):
            dl = self.selected_dataset_data.create_dataline(case)
            qlwt = QListWidgetItem()
            dl.plots = self.csd.case_render_cb.currentIndex()
            dl.transform = self.csd.case_transform_cb.currentIndex()
            dl.xsource = self.csd.case_xdata_cb.currentText()
            dl.xscale = self.csd.case_xscale_sb.value()
            dl.xoffset = self.csd.case_xoffset_sb.value()
            dl.ysource = self.csd.case_ydata_cb.currentText()
            dl.yscale = self.csd.case_yscale_sb.value()
            dl.yoffset = self.csd.case_yoffset_sb.value()
            if(self.csd.case_randomcol_rb.isChecked()):
                dl.color = ["#"+''.join([random.choice('0123456789ABCDEF') for i in range(6)])][0]
            elif(self.csd.case_presetcol_rb.isChecked()):
                colorpalette_i = self.csd.case_palettecol_cb.currentIndex()
                colorpalette = self.csd.COLOR_LIST[colorpalette_i]
                dl.color = colorpalette[color_iter]
                color_iter += 1
                if(color_iter == len(colorpalette)):
                    color_iter = 0
            else:
                dl.color = self.csd.color
            dl.linestyle = self.csd.case_style_cb.currentText()
            dl.linewidth = self.csd.case_linewidth_sb.value()
            dl.markerstyle = self.csd.case_marker_cb.currentText()
            dl.markersize = self.csd.case_markersize_sb.value()
            if(self.csd.case_inforname_rb.isChecked()):
                dstitle = self.selected_dataset_data.title 
                dscases = self.selected_dataset_data.casenames
                if(case < len(dscases)):
                    dl.name = dstitle + ' ' + dscases[case]
            qlwt.setText(dl.name)
            dl.name = dl.name if self.csd.case_addlegend_cb.isChecked() else '_' + dl.name
            qlwt.setData(Qt.UserRole, dl)
            self.dataline_list.insertItem(dli, qlwt)
            self.datalines[self.dataset_list.currentRow()].append(dl)
        self.updatePlots()

    def populateSelectedDatasetDetails(self, listitemwidget, qlistwidget):
        if(not listitemwidget):
            self.setDatasetControlsStatus(False)
            self.ds_title_edit.setText('')
            self.ds_casenum_lb.setText('0')
            self.ds_info_lb.setText('')
            return
        self.setDatasetControlsStatus(True)
        self.ds_title_edit.setText(listitemwidget.text())
        self.selected_dataset_widget = listitemwidget
        self.selected_dataset_data = listitemwidget.data(Qt.UserRole)
        isTF = self.selected_dataset_data.type in ['TF', 'filter']
        self.ds_poleszeros_btn.setEnabled(isTF)
        self.resp_btn.setEnabled(isTF)
        self.ds_casenum_lb.setText(str(len(self.selected_dataset_data.data)))
        self.ds_caseadd_btn.setVisible(len(self.selected_dataset_data.data) > 1)
        self.ds_info_lb.setText(self.selected_dataset_data.miscinfo)

        #relleno las cajas del filtro
        if(self.selected_dataset_data.type == 'filter'):
            self.populateSelectedFilterDetails()

    
    def populateSelectedFilterDetails(self, index=-2):
        pass

    def updateSelectedDatasetName(self):
        new_title = self.ds_title_edit.text()
        self.selected_dataset_widget.setText(new_title)
        self.selected_dataset_data.title = new_title
        if(self.selected_dataset_data.type == 'filter'):
            self.selfil_cb.setItemText(self.selfil_cb.currentIndex(), new_title)
            self.stages_selfil_cb.setItemText(self.stages_selfil_cb.currentIndex(), new_title)
            self.filtername_box.setText(new_title)

    def populateSelectedDatalineDetails(self, listitemwidget, qlistwidget):
        if(not listitemwidget):
            self.setDatalineControlsStatus(False)
            self.dl_name_edit.setText('')
            return
        self.setDatalineControlsStatus(True)
        self.dl_xscale_sb.blockSignals(True)
        self.dl_yscale_sb.blockSignals(True)
        self.dl_xoffset_sb.blockSignals(True)
        self.dl_yoffset_sb.blockSignals(True)
        self.dl_linewidth_sb.blockSignals(True)
        self.dl_markersize_sb.blockSignals(True)
        self.dl_savgol_wlen.blockSignals(True)
        self.dl_savgol_ord.blockSignals(True)

        self.selected_dataline_widget = listitemwidget
        self.selected_dataline_data = listitemwidget.data(Qt.UserRole)
        self.dl_name_edit.setText(self.selected_dataline_widget.text())
        self.dl_render_cb.setCurrentIndex(self.selected_dataline_data.plots)
        
        self.dl_xdata_cb.clear()
        self.dl_ydata_cb.clear()
        self.dl_xdata_cb.addItems(self.selected_dataline_data.dataset.fields)
        self.dl_ydata_cb.addItems(self.selected_dataline_data.dataset.fields)
        
        self.dl_transform_cb.setCurrentIndex(self.selected_dataline_data.transform)
        self.dl_xdata_cb.setCurrentText(self.selected_dataline_data.xsource)
        self.dl_xscale_sb.setValue(self.selected_dataline_data.xscale)
        self.dl_xoffset_sb.setValue(self.selected_dataline_data.xoffset)
        self.dl_ydata_cb.setCurrentText(self.selected_dataline_data.ysource)
        self.dl_yscale_sb.setValue(self.selected_dataline_data.yscale)
        self.dl_yoffset_sb.setValue(self.selected_dataline_data.yoffset)
        self.dl_color_edit.setText(self.selected_dataline_data.color)
        self.dl_style_cb.setCurrentText(self.selected_dataline_data.linestyle)
        self.dl_linewidth_sb.setValue(self.selected_dataline_data.linewidth)
        self.dl_marker_cb.setCurrentText(self.selected_dataline_data.markerstyle)
        self.dl_markersize_sb.setValue(self.selected_dataline_data.markersize)
        self.dl_color_label.setStyleSheet(f'background-color: {self.selected_dataline_data.color}')
        self.dl_savgol_wlen.setValue(self.selected_dataline_data.savgolwindow)
        self.dl_savgol_ord.setValue(self.selected_dataline_data.savgolord)
        
        self.dl_xscale_sb.blockSignals(False)
        self.dl_yscale_sb.blockSignals(False)
        self.dl_xoffset_sb.blockSignals(False)
        self.dl_yoffset_sb.blockSignals(False)
        self.dl_linewidth_sb.blockSignals(False)
        self.dl_markersize_sb.blockSignals(False)
        self.dl_savgol_wlen.blockSignals(False)
        self.dl_savgol_ord.blockSignals(False)
        self.updatePlots()

    def updateSelectedDataline(self):
        self.saveFile(True)
        if(not self.selected_dataline_widget):
            return
        new_name = self.dl_name_edit.text()
        self.selected_dataline_widget.setText(new_name)
        self.selected_dataline_data.name = new_name
        self.selected_dataline_data.plots = self.dl_render_cb.currentIndex()
        self.selected_dataline_data.transform = self.dl_transform_cb.currentIndex()
        self.selected_dataline_data.xsource = self.dl_xdata_cb.currentText()
        self.selected_dataline_data.xscale = self.dl_xscale_sb.value()
        self.selected_dataline_data.xoffset = self.dl_xoffset_sb.value()
        self.selected_dataline_data.ysource = self.dl_ydata_cb.currentText()
        self.selected_dataline_data.yscale = self.dl_yscale_sb.value()
        self.selected_dataline_data.yoffset = self.dl_yoffset_sb.value()
        self.selected_dataline_data.color = self.dl_color_edit.text()
        self.selected_dataline_data.linestyle = self.dl_style_cb.currentText()
        self.selected_dataline_data.linewidth = self.dl_linewidth_sb.value()
        self.selected_dataline_data.markerstyle = self.dl_marker_cb.currentText()
        self.selected_dataline_data.markersize = self.dl_markersize_sb.value()
        self.selected_dataline_data.savgolwindow = self.dl_savgol_wlen.value()
        self.selected_dataline_data.savgolord = self.dl_savgol_ord.value()
        self.populateSelectedDatalineDetails(self.selected_dataline_widget, None)
        self.updatePlots()

    
    def openColorPicker(self):
        dialog = QColorDialog(self)
        dialog.setCurrentColor(Qt.red)
        dialog.setOption(QColorDialog.ShowAlphaChannel)
        dialog.open()
        dialog.currentColorChanged.connect(self.updateDatalineColor)

    def updateDatalineColor(self, color):
        self.dl_color_edit.setText(color.name())
        self.dl_color_label.setStyleSheet(f'background-color: {color.name()}')
        self.selected_dataline_data.color = color.name()
        self.updatePlots()

    def setDatasetControlsStatus(self, enabled=True):
        self.ds_title_edit.setEnabled(enabled)
        self.ds_addline_btn.setEnabled(enabled)
        self.ds_caseadd_btn.setEnabled(enabled)
        self.ds_remove_btn.setEnabled(enabled)

    def setDatalineControlsStatus(self, enabled=True):
        self.dl_name_edit.setEnabled(enabled)
        self.dl_render_cb.setEnabled(enabled)
        self.dl_transform_cb.setEnabled(enabled)
        self.dl_xdata_cb.setEnabled(enabled)
        self.dl_xscale_sb.setEnabled(enabled)
        self.dl_xoffset_sb.setEnabled(enabled)
        self.dl_ydata_cb.setEnabled(enabled)
        self.dl_yscale_sb.setEnabled(enabled)
        self.dl_yoffset_sb.setEnabled(enabled)
        self.dl_color_edit.setEnabled(enabled)
        self.dl_color_pickerbtn.setEnabled(enabled)
        self.dl_style_cb.setEnabled(enabled)
        self.dl_linewidth_sb.setEnabled(enabled)
        self.dl_marker_cb.setEnabled(enabled)
        self.dl_markersize_sb.setEnabled(enabled)
        self.dl_savgol_wlen.setEnabled(enabled)
        self.dl_savgol_ord.setEnabled(enabled)
        self.dl_remove_btn.setEnabled(enabled)

    def getPlotFromIndex(self, plotnum):
        x = plotnum
        tab = 0
        for tab_plots in self.plots_canvases:
            if(x - len(tab_plots) >= 0):
                tab += 1
                x -= len(tab_plots)
            else:
                break
        return self.plots_canvases[tab][x]

    def autoscalePlots(self):
        processedCanvas = [x.canvas for x in self.plots_canvases[self.tabbing_plots.currentIndex()]]
        for canvas in processedCanvas:
            canvas.ax.margins(self.plt_marginx.value(), self.plt_marginy.value())
            canvas.ax.relim()
            canvas.ax.autoscale()
        self.updatePlots()

    def changeLabelSize(self):
        # plt.rcParams.update({'font.size': self.plt_labelsize_sb.value()})
        self.updatePlots()
    
        
    def updatePlots(self):
        self.saveFile(True)
        processedCanvas = [x.canvas for x in self.plots_canvases[self.tabbing_plots.currentIndex()]]
        for canvas in processedCanvas:
            plotlist = []
            for artist in canvas.ax.lines + canvas.ax.collections:
                artist.remove()
            for x in range(self.dataset_list.count()):
                ds = self.dataset_list.item(x).data(Qt.UserRole)
                for dl in ds.datalines:
                    dl_canvas = self.getPlotFromIndex(dl.plots).canvas
                    if(dl_canvas == canvas):
                        
                        for label in (canvas.ax.get_xticklabels() + canvas.ax.get_yticklabels()):
                            label.set_fontsize(self.plt_ticksize_sb.value())
                        canvas.ax.xaxis.label.set_size(self.plt_labelsize_sb.value())
                        canvas.ax.yaxis.label.set_size(self.plt_labelsize_sb.value())
                        canvas.ax.title.set_size(self.plt_titlesize_sb.value())

                        x, y = ds.get_datapoints(dl.xsource, dl.ysource, dl.casenum)

                        if(dl.transform == 1):
                            y = np.abs(y)
                        elif(dl.transform == 2):
                            y = np.angle(y, deg=True)
                        elif(dl.transform == 3):
                            y = np.unwrap(np.angle(y, deg=True), period=360)
                        elif(dl.transform == 4):
                            y = 20 * np.log10(y)
                        elif(dl.transform == 5):
                            y = 20 * np.log10(np.abs(y))
                        elif(dl.transform == 6):
                            y = np.unwrap(y, period=360)
                        else:
                            y = np.real(y)

                        if(dl.transform in [2,3,6]):
                            canvas.ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins='auto', steps=[1.8,2.25,4.5,9]))
                        else:
                            canvas.ax.yaxis.set_major_locator(ticker.AutoLocator())

                        try:
                            savgolw = int(dl.savgolwindow)
                            if(savgolw <= len(x)):
                                savgolo = int(dl.savgolord)
                                y = y if savgolw <= savgolo else savgol_filter(y, savgolw, savgolo)
                        except ValueError:
                            pass

                        try:
                            line, = canvas.ax.plot(
                                x * dl.xscale + dl.xoffset,
                                y * dl.yscale + dl.yoffset,
                                linestyle = LINE_STYLES[dl.linestyle],
                                linewidth = dl.linewidth,
                                marker = MARKER_STYLES[dl.markerstyle],
                                markersize = dl.markersize,
                                color = dl.color,
                                label = dl.name,
                            )
                            if(dl.name != '' and dl.name[0] != '_'):
                                plotlist.append(line)
                        
                        except ValueError:
                            self.statusbar.showMessage('Wrong data source matching', 2000)
            if(self.selected_dataline_data):
                lmancanvas = self.getPlotFromIndex(self.selected_dataline_data.plots).canvas
                if(canvas == lmancanvas):
                    if(self.lman):
                        self.lman.loc = self.plt_legendpos.currentIndex()
                        self.lman.process_selected_data(self.lman.selected_indices)
                    try:
                        x, y = ds.get_datapoints(self.selected_dataline_data.xsource, self.selected_dataline_data.ysource, self.selected_dataline_data.casenum)
                        self.lman = LassoManager(lmancanvas, [x*self.selected_dataline_data.xscale + self.selected_dataline_data.xoffset,
                                                              y * self.selected_dataline_data.yscale + self.selected_dataline_data.yoffset],
                                                 self.selected_dataline_data.color,self.flags, self.plt_legendpos.currentIndex())
                    except:
                        pass
                    

            if(self.plt_legendpos.currentText() == 'None'):
                try:
                    canvas.ax.get_legend().remove()
                except:
                    pass
            else:
                canvas.ax.legend(handles=plotlist, fontsize=self.plt_legendsize_sb.value(), loc=self.plt_legendpos.currentIndex())
            if(self.plt_grid.isChecked()):
                canvas.ax.grid(True, which="both", linestyle=':')
            else:
                canvas.ax.grid(False)
        
            try:
                canvas.draw()
            except ParseSyntaxException or ValueError:
                pass
        
    def showZPWindow(self):
        zeros = self.selected_dataset_data.zeros[0]
        poles = self.selected_dataset_data.poles[0]
        self.zpWindow = ZPWindow(zeros, poles, self.selected_dataset_data.title)
        self.zpWindow.show()

    def newFile(self):
        self.droppedFiles = []
        self.datasets = []
        self.datalines = []
        self.selected_dataset_widget = {}
        self.selected_dataline_widget = {}
        self.selected_dataset_data = {}
        self.selected_dataline_data = {}
        self.zpWindow = type(ZPWindow, (), {})()
        self.updateAll()
    
    def saveFile(self, noprompt=False):
        if(noprompt):
            filename = 'temp.fto'
        else:
            filename, _ = QFileDialog.getSaveFileName(self,"Save File", "","Filter tool file (*.fto)")
        if(not filename): return
        with open(filename, 'wb') as f:
            flat_plots_canvas = [item.canvas for sublist in self.plots_canvases for item in sublist]
            plots_data = []
            for canv in flat_plots_canvas:
                plots_data.append(canv.get_properties())
            general_config = {
                'labelsize_sb': self.plt_labelsize_sb.value(),
                'legendsize_sb': self.plt_legendsize_sb.value(),
                'ticksize_sb': self.plt_ticksize_sb.value(),
                'titlesize_sb': self.plt_titlesize_sb.value(),
                'legendpos': self.plt_legendpos.currentIndex(),
                'grid': self.plt_grid.isChecked(),
                'marginx': self.plt_marginx.value(),
                'marginy': self.plt_marginy.value()      
            }
            d = [self.datasets, self.datalines, plots_data, general_config]
            pickle.dump(d, f, pickle.HIGHEST_PROTOCOL)

    def loadFile(self):
        filename, _ = QFileDialog.getOpenFileName(self,"Select files", "","Filter tool file (*.fto)")
        if(not filename): return
        with open(filename, 'rb') as f:
            f.seek(0)
            self.datasets, self.datalines, plotdata, general_config = pickle.load(f)            
            self.plt_labelsize_sb.setValue(general_config['labelsize_sb'])
            self.plt_legendsize_sb.setValue(general_config['legendsize_sb'])
            self.plt_ticksize_sb.setValue(general_config['ticksize_sb'])
            self.plt_titlesize_sb.setValue(general_config['titlesize_sb'])
            self.plt_legendpos.setCurrentIndex(general_config['legendpos'])
            self.plt_grid.setChecked(general_config['grid'])
            self.plt_marginx.setValue(general_config['marginx'])
            self.plt_marginy.setValue(general_config['marginy'])  
            acc = 0   
            for s in self.plots_canvases:
                for p in s:
                    p.canvas.restore_properties(plotdata[acc])
                    acc += 1
            for ds in self.datasets:
                qlwt = QListWidgetItem()
                qlwt.setData(Qt.UserRole, ds)
                qlwt.setText(ds.title)
                self.dataset_list.addItem(qlwt)
                for dl in ds.datalines:
                    qlwt = QListWidgetItem()
                    qlwt.setData(Qt.UserRole, dl)
                    qlwt.setText(dl.name)
                    self.dataline_list.addItem(qlwt)
                if(ds.type == 'filter'):
                    self.filters.append(ds)
                    self.selfil_cb.blockSignals(True)
                    self.stages_selfil_cb.blockSignals(True)
                    self.selfil_cb.addItem(ds.title, ds)
                    self.stages_selfil_cb.addItem(ds.title, ds)
                    self.selfil_cb.blockSignals(False)
                    self.stages_selfil_cb.blockSignals(False)

            self.dataset_list.setCurrentRow(self.dataset_list.count() - 1)
            self.updateAll()
    
    def getFlags(self, index):
        if index == 0:
            self.flags[index] = self.Maximo.isChecked()
        elif index == 1:
            self.flags[index] = self.Minimo.isChecked()
        elif index == 2:
            self.flags[index] = self.Pendiente.isChecked()
        elif index == 3:
            self.flags[index] = self.Promedio.isChecked()
        else:
              self.flags[index] = self.Rms.isChecked()
    
    def updateAll(self):
        self.updatePlots()
        self.updateSelectedDataline()
        self.updateFilterParametersAvailable()
    
    def getRelevantFrequencies(self, zeros, poles):
        singularitiesNorm = np.append(np.abs(zeros), np.abs(poles))
        singularitiesNormWithoutZeros = singularitiesNorm[singularitiesNorm!=0]
        if(len(singularitiesNormWithoutZeros) == 0):
            return (1, 1)
        return (np.min(singularitiesNormWithoutZeros), np.max(singularitiesNormWithoutZeros))
    
    def getMultiplierAndPrefix(self, val):
        multiplier = 1
        prefix = ''
        if(val < 1e-7):
            multiplier = 1e9
            prefix = 'n'
        elif(val < 1e-4):
            multiplier = 1e-6
            prefix = 'μ'
        elif(val < 1e-1):
            multiplier = 1e-3
            prefix = 'm'
        elif(val < 1e2):
            multiplier = 1
            prefix = ''
        elif(val < 1e5):
            multiplier = 1e3
            prefix = 'k'
        elif(val < 1e8):
            multiplier = 1e6
            prefix = 'M'
        elif(val > 1e11):
            multiplier = 1e9
            prefix = 'G'
        return (multiplier, prefix)

