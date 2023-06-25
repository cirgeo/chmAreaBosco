# -*- coding: utf-8 -*-

"""
/***************************************************************************
 CHMtoForest
                                 A QGIS plugin
 Converts a CHM to a raster layer with forest polygons according to various definitions
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2023-05-27
        copyright            : (C) 2023 by Francesco Pirotti - CIRGEO/TESAF University of Padova
        email                : francesco.pirotti@unipd.it
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = 'Francesco Pirotti - CIRGEO/TESAF University of Padova'
__date__ = '2023-05-27'
__copyright__ = '(C) 2023 by Francesco Pirotti - CIRGEO/TESAF University of Padova'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

import math
import shutil

import numpy as np
#import tempfile
from qgis.PyQt.Qt import *
from qgis.PyQt.QtGui import *
from qgis.core import *
from qgis.utils import *
import inspect
import sys
from datetime import datetime
import os
#from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFileDestination)

dirname, filename = os.path.split(os.path.abspath(__file__))
sys.path.append(dirname)
import cv2 as cv
from osgeo import gdal
import processing
class CHMtoForestAlgorithm(QgsProcessingAlgorithm):
    """
    This is an example algorithm that takes a vector layer and
    creates a new identical one.

    It is meant to be used as an example of how to create your own
    algorithms and explain methods and variables used to do it. An
    algorithm like this will be available in all elements, and there
    is not need for additional work.

    All Processing algorithms should extend the QgsProcessingAlgorithm
    class.
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    tmpdir = ''
    OUTPUT = 'OUTPUT'
    OUTPUT_V = 'OUTPUT_V'
    INPUT = 'INPUT'
    INPUT_SIBOSCO = 'INPUT_SIBOSCO'
    INPUT_NOBOSCO = 'INPUT_NOBOSCO'
    # PERC_COVER = 'PERC_COVER'
    # MIN_AREA = 'MIN_AREA'
    # MIN_LARGH = 'MIN_LARGH'
    # ALTEZZA_MIN_ALBERO = 'ALTEZZA_MIN_ALBERO'

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """

        # We add the input vector features source. It can have any kind of
        # geometry.
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                self.tr('Input CHM')
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_SIBOSCO,
                self.tr('Input Maschera Pixel Bosco'),
                optional=True, defaultValue=None
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_NOBOSCO,
                self.tr('Input Maschera Pixel No-Bosco'),
                optional=True, defaultValue=None
            )
        )
        # We add a feature sink in which to store our processed features (this
        # usually takes the form of a newly created vector layer when the
        # algorithm is run in QGIS).
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                self.tr('Area Bosco Raster'),
                createByDefault=True,
                optional=True,
            )
        )
        self.addParameter(QgsProcessingParameterVectorDestination(self.OUTPUT_V,
                                                                  self.tr('Area Bosco Vettoriale'),
                                                                  type=QgsProcessing.TypeVectorPolygon,
                                                                  createByDefault=False,
                                                                  optional=True,
                                                                  defaultValue=None))

        self.addParameter(
            QgsProcessingParameterNumber(
                'altezza_alberochioma_m',
                self.tr('Soglia altezza chioma (m)'),
                defaultValue=2.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'densit_minima_percentuale',
                self.tr('Densità copertura (%)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=20.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'area_minima_m2',
                self.tr('Area minima (m2)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=2000.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'larghezza_minima_m',
                self.tr('Larghezza minima'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=20.0
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        feedback = QgsProcessingMultiStepFeedback(11, feedback)
        results = {}
        outputs = {}
        start = datetime.now()
        source = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        sourceNoBosco = self.parameterAsRasterLayer(parameters, self.INPUT_NOBOSCO, context)
        sourceSiBosco = self.parameterAsRasterLayer(parameters, self.INPUT_SIBOSCO, context)
        temppathfile = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        temppathfile_v = self.parameterAsFileOutput(parameters, self.OUTPUT_V, context)

        # ret, markers = cv.connectedComponents(sure_fg)
        # https://docs.opencv.org/4.x/d3/db4/tutorial_py_watershed.html
        ksize  = parameters['larghezza_minima_m']
        ksizePixels = ksize/source.rasterUnitsPerPixelX()
        minArea = parameters['area_minima_m2']
        ksizeGaps = math.sqrt(parameters['area_minima_m2'] / 3.14)
        ksizeGapsPixels = math.sqrt(parameters['area_minima_m2'] / 3.14)/source.rasterUnitsPerPixelX()
        areaPixel = source.rasterUnitsPerPixelX()*source.rasterUnitsPerPixelX()

        feedback.setProgressText("Lato pixel... " + str(source.rasterUnitsPerPixelX()))
        feedback.setProgressText("CRS... " + str(source.crs()))
        feedback.setProgressText("NBande... " + str(source.bandCount()))
        # pipe = QgsRasterPipe()
        # sdp = source.dataProvider()
        if source.bandCount() != 1:
            feedback.reportError('Il raster CHM deve avere solamente una banda - il file ' +
                                 str(source.source()) + ' ha ' + str(source.bandCount()) + ' bande!'
                                 )
            return {}


        translate_options = gdal.TranslateOptions(format='GTiff', outputType=gdal.GDT_Byte)

        try:
           gdal.Translate(srcDS=str(source.source()),
                       destName=temppathfile,
                       options=translate_options)
        except:
            feedback.reportError('Non sono riuscito ad implementare il raster in uscita - ' +
                                 gdal.GetLastErrorMsg() )
            return {}

        tempRasterLayer = QgsRasterLayer(temppathfile)
        provider = tempRasterLayer.dataProvider()
        feedback.setProgressText("Creato il raster temporaneo " + provider.name() +
                                 " di tipo " +  str(provider.bandScale(0)) +
                                 " - dimensione pixel: " + str( provider.xSize()) +
                                 " x " + str(provider.ySize()))
        block = provider.block(1, provider.extent(), provider.xSize(), provider.ySize())

        if provider is None:
            feedback.reportError('Cannot find or read ' + tempRasterLayer.source())
            return {}

        feedback.setProgressText("Leggo il raster")

        try:
            ds = gdal.Open(str(source.source()))
        except:
            feedback.reportError('Non sono riuscito a leggere il raster CHM ' +
                                 gdal.GetLastErrorMsg() )
            return {}

        img = np.array(ds.GetRasterBand(1).ReadAsArray())
        feedback.setProgressText("Letto raster di dimensioni "+ str(img.shape))
        #img = cv.imread(source.source(), cv.IMREAD_ANYDEPTH | cv.IMREAD_GRAYSCALE )  #cv.IMREAD_GRAYSCALE
        if img is None:
            feedback.reportError('Errore nella lettura con opencv del CHM ' + source.source())
            return {}

        # Check for cancelation
        if feedback.isCanceled():
            return {}
        feedback.setProgressText("Dimensione immagine: " + ' x '.join(map(str, img.shape)))
        feedback.setProgressText("Applico soglia di altezza di : " +
                                 str(parameters['altezza_alberochioma_m']) + ' metri ')
        # binarize the image
        binr = cv.threshold(img, parameters['altezza_alberochioma_m'], 1, cv.THRESH_BINARY)[1]
        if feedback.isCanceled():
            return {}

        feedback.setProgressText("Creo un kernel di : " + str(round(ksizePixels, 2)) +
                                 '(' + str(int(ksizePixels)) +
                                 ') metri  e larghezza minima ' + str(parameters['larghezza_minima_m']))
        kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (int(ksizePixels), int(ksizePixels)))
        if feedback.isCanceled():
            return {}

        chmBinary = binr
        feedback.setProgressText("Processo CLOSING  raster")
        closing = cv.morphologyEx(chmBinary, cv.MORPH_CLOSE, kernel)
        if feedback.isCanceled():
            return {}
        feedback.setProgressText("Processo OPENING  raster")
        opening =  cv.morphologyEx(closing.astype('B'), cv.MORPH_OPEN, kernel)
        if feedback.isCanceled():
            return {}
        final = opening

        feedback.setProgressText("Rimuovo piccole aree  bosco...")
        contours, _ = cv.findContours(final.astype('B'), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        feedback.setProgressText("Trovato " + str(len(contours)) + " aree bosco...")
        for i in range(len(contours)):
            aa = int(cv.contourArea(contours[i])*areaPixel)
            if aa < minArea:
                cv.drawContours(final, contours, i, 0, -1)

        if feedback.isCanceled():
            return {}

        feedback.setProgressText("Rimuovo piccole aree NON bosco e metto a bosco....")
        finalInv = ((final - 1) * -1).astype('B')
        if feedback.isCanceled():
            return {}
        contours, _ = cv.findContours(finalInv, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        feedback.setProgressText("Trovato " + str(len(contours)) + " aree NON bosco...")
        if feedback.isCanceled():
            return {}

        for i in range(len(contours)):
            aa = int(cv.contourArea(contours[i])*areaPixel )
            if aa < minArea:
                cv.drawContours(final, contours, i, 1, -1)

        feedback.setProgressText("Scrivo i dati....")
        provider.setEditable(True)
        data = bytearray(bytes(final.astype('B')))
        if feedback.isCanceled():
            return {}
        block.setData(data)
        if feedback.isCanceled():
            return {}
        writeok = provider.writeBlock(block, 1)
        if feedback.isCanceled():
            return {}
        if writeok:
            feedback.setProgressText("Successo nella scrittura del dato")
        else:
            feedback.reportError("Non sono riuscito a scrivere il blocco raster")
            return {}
        provider.setEditable(False)
        if feedback.isCanceled():
            return {}

        ### MASCHERA CON ESISTENTI ####
        if sourceSiBosco is not None or sourceNoBosco is not None:
            parameters = {'INPUT_A': tempRasterLayer,
                          'BAND_A': 1,
                          'FORMULA': 'A',
                          # your expression here. Mine finds all cells with value > 100. Experiment in the GUI if needed. You can copy and paste exactly the same expression to into your code here
                          'OUTPUT': temppathfile}
            finalCalc = None
            if sourceSiBosco is not None:
                if sourceSiBosco.bandCount() != 1:
                    feedback.reportError('Il raster bosco deve avere solamente una banda - il file ' +
                                         str(sourceSiBosco.source()) + ' ha ' + str(
                        sourceSiBosco.bandCount()) + ' bande! Procedo senza includere questo raster'
                                         )
                else:
                    if sourceSiBosco.crs() != source.crs():
                        feedback.setProgressText("CRS SiBosco diverso, " + sourceSiBosco.crs() +
                                                 " convergo...")
                        alg_params = {
                            'DATA_TYPE': 1,  # Byte
                            'EXTRA': '',
                            'INPUT': sourceSiBosco,
                            'MULTITHREADING': True,
                            'NODATA': None,
                            'OPTIONS': '',
                            'RESAMPLING': 0,  # Vicino più Prossimo
                            'SOURCE_CRS': sourceSiBosco,
                            'TARGET_CRS': source,
                            'TARGET_EXTENT': source,
                            'TARGET_EXTENT_CRS': source,
                            'TARGET_RESOLUTION': source,
                            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                        }
                        TrasformazioneRiproiezione = processing.run('gdal:warpreproject', alg_params,
                                                                               context=context, feedback=feedback,
                                                                                 is_child_algorithm=True)
                        sourceSiBosco = QgsRasterLayer(TrasformazioneRiproiezione['OUTPUT'])

                    feedback.setProgressText("Integro Raster Si-Bosco ....")
                    alg_params = {
                        'BAND_A': 1,
                        'BAND_B': 1,
                        'EXTENT_OPT': 3,  # Intersect
                        'EXTRA': '',
                        'FORMULA': 'A * (B == 1)',
                        'INPUT_A': source,
                        'INPUT_B': sourceSiBosco,
                        'NO_DATA': 0,
                        'OPTIONS': '',
                        'PROJWIN': source,
                        'RTYPE': 0,  # Byte
                        'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                    }
                    CalcolatoreRaster = processing.run('gdal:rastercalculator', alg_params, context=context,
                                                                  feedback=feedback, is_child_algorithm=True)

                    finalCalc = QgsRasterLayer(CalcolatoreRaster['OUTPUT'])

            if sourceNoBosco is not None:
                if sourceNoBosco.bandCount() != 1:
                    feedback.reportError('Il raster bosco deve avere solamente una banda - il file ' +
                                         str(sourceNoBosco.source()) + ' ha ' + str(
                        sourceNoBosco.bandCount()) + ' bande! Procedo senza includere questo raster'
                                         )
                else:
                    if sourceNoBosco.crs() != source.crs():
                        feedback.setProgressText("CRS SiBosco diverso, " + sourceNoBosco.crs() +
                                                 " convergo...")
                        alg_params = {
                            'DATA_TYPE': 1,  # Byte
                            'EXTRA': '',
                            'INPUT': sourceNoBosco,
                            'MULTITHREADING': True,
                            'NODATA': None,
                            'OPTIONS': '',
                            'RESAMPLING': 0,  # Vicino più Prossimo
                            'SOURCE_CRS': sourceNoBosco,
                            'TARGET_CRS': source,
                            'TARGET_EXTENT': source,
                            'TARGET_EXTENT_CRS': source,
                            'TARGET_RESOLUTION': source,
                            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                        }
                        TrasformazioneRiproiezione = processing.run('gdal:warpreproject', alg_params,
                                                                               context=context, feedback=feedback,
                                                                                 is_child_algorithm=True)
                        sourceNoBosco = QgsRasterLayer(TrasformazioneRiproiezione['OUTPUT'])

                    feedback.setProgressText("Integro Raster Si-Bosco ....")
                    alg_params = {
                        'BAND_A': 1,
                        'BAND_B': 1,
                        'EXTENT_OPT': 3,  # Intersect
                        'EXTRA': '',
                        'FORMULA': 'A * (B == 1)',
                        'INPUT_A': source,
                        'INPUT_B': sourceNoBosco,
                        'NO_DATA': 0,
                        'OPTIONS': '',
                        'PROJWIN': source,
                        'RTYPE': 0,  # Byte
                        'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
                    }
                    if finalCalc is not None:
                        alg_params['INPUT_A'] = finalCalc

                    CalcolatoreRaster = processing.run('gdal:rastercalculator', alg_params, context=context,
                                                                  feedback=feedback, is_child_algorithm=True)

                    temppathfile = CalcolatoreRaster['OUTPUT']




        feedback.setProgressText(temppathfile)
        out_rlayer = QgsRasterLayer(temppathfile, "Area Foresta hTrees="+
                                    str(parameters['altezza_alberochioma_m']) +
                                    " k(m)="+str(int(ksize)) )

        mess, success = out_rlayer.loadNamedStyle(dirname+"/extra/style.qml")
        if success is False:
            feedback.reportError( mess + " - " + dirname+"/extra/style.qml")
        else:
            feedback.setProgressText(mess)
        QgsProject.instance().addMapLayer(out_rlayer)
        # Poligonizzazione (da raster a vettore)

        alg_params = {
            'BAND': 1,
            'CREATE_3D': False,
            'EXTRA': '',
            'FIELD_NAME_MAX': '',
            'FIELD_NAME_MIN': '',
            'IGNORE_NODATA': False,
            'INPUT': out_rlayer,
            'INTERVAL': 1,
            'NODATA': 0,
            'OFFSET': 0,
            'OUTPUT': temppathfile_v
        }
        if temppathfile_v:
            feedback.setProgressText(" ")
            feedback.setProgressText("==========================")
            feedback.setProgressText("Esporto un livello vettoriale....")

            outputsp =  processing.run('gdal:contour_polygon', alg_params, context=context, feedback=feedback,
                           is_child_algorithm=True)

            temppathfile_vector = outputsp['OUTPUT']
            feedback.setProgressText(outputsp['OUTPUT'])
            out_vlayer = QgsVectorLayer(temppathfile_vector, "Area Foresta" )

            mess, success = out_vlayer.loadNamedStyle(dirname + "/extra/stylev.qml")
            if success is False:
                feedback.reportError(mess + " - " + dirname + "/extra/stylev.qml")
            else:
                feedback.setProgressText(mess)
            QgsProject.instance().addMapLayer(out_vlayer)


        #QgsProject.instance().addMapLayer(outputsp['OUTPUT'])
        #self.iface.mapCanvas().refresh()

        feedback.setProgressText(temppathfile_v )


        stop = datetime.now()
        feedback.setProgressText("Tempo di elaborazione: " + str(stop-start))
        # Return the results of the algorithm. In this case our only result is
        # the feature sink which contains the processed features, but some
        # algorithms may return multiple feature sinks, calculated numeric
        # statistics, etc. These should all be included in the returned
        # dictionary, with keys matching the feature corresponding parameter
        # or output names.
        #return {self.OUTPUT: temppathfile}
        return results
    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'CHM => Bosco'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr(self.name())

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr(self.groupId())

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return ''

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CHMtoForestAlgorithm()
