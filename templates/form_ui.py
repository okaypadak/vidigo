# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'form.ui'
#
# Created by: PyQt5 UI code generator 5.15.9
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_Form(object):
    def setupUi(self, Form):
        Form.setObjectName("Form")
        Form.resize(600, 400)
        self.verticalLayout = QtWidgets.QVBoxLayout(Form)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label_url = QtWidgets.QLabel(Form)
        self.label_url.setObjectName("label_url")
        self.verticalLayout.addWidget(self.label_url)
        self.urlInput = QtWidgets.QLineEdit(Form)
        self.urlInput.setObjectName("urlInput")
        self.verticalLayout.addWidget(self.urlInput)
        self.label_engine = QtWidgets.QLabel(Form)
        self.label_engine.setObjectName("label_engine")
        self.verticalLayout.addWidget(self.label_engine)
        self.engineSelect = QtWidgets.QComboBox(Form)
        self.engineSelect.setObjectName("engineSelect")
        self.engineSelect.addItem("")
        self.engineSelect.addItem("")
        self.engineSelect.addItem("")
        self.engineSelect.addItem("")
        self.verticalLayout.addWidget(self.engineSelect)
        self.transcribeButton = QtWidgets.QPushButton(Form)
        self.transcribeButton.setObjectName("transcribeButton")
        self.verticalLayout.addWidget(self.transcribeButton)
        self.label_result = QtWidgets.QLabel(Form)
        self.label_result.setObjectName("label_result")
        self.verticalLayout.addWidget(self.label_result)
        self.resultOutput = QtWidgets.QTextEdit(Form)
        self.resultOutput.setObjectName("resultOutput")
        self.verticalLayout.addWidget(self.resultOutput)

        self.retranslateUi(Form)
        QtCore.QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        _translate = QtCore.QCoreApplication.translate
        Form.setWindowTitle(_translate("Form", "YouTube / Udemy Transcriber"))
        self.label_url.setText(_translate("Form", "Video URL:"))
        self.label_engine.setText(_translate("Form", "Engine Seçimi:"))
        self.engineSelect.setItemText(0, _translate("Form", "auto"))
        self.engineSelect.setItemText(1, _translate("Form", "whisper"))
        self.engineSelect.setItemText(2, _translate("Form", "vosk"))
        self.engineSelect.setItemText(3, _translate("Form", "deepspeech"))
        self.transcribeButton.setText(_translate("Form", "Transcribe"))
        self.label_result.setText(_translate("Form", "Transkript:"))
