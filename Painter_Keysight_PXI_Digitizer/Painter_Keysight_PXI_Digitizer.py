#!/usr/bin/env python
import sys
sys.path.append('C:\Program Files (x86)\Keysight\SD1\Libraries\Python')

from BaseDriver import LabberDriver, Error, IdError
import keysightSD1

import numpy as np


class Driver(LabberDriver):
    """ This class implements the Keysight PXI digitizer"""

    def performOpen(self, options={}):
        """Perform the operation of opening the instrument connection"""
        # set time step and resolution
        self.nBit = 16
        self.bitRange = float(2**(self.nBit-1)-1)
        # timeout
        self.timeout_ms = int(1000 * self.dComCfg['Timeout'])
        # get PXI chassis
        self.chassis = int(self.dComCfg.get('PXI chassis', 1))
        # create AWG instance
        self.dig = keysightSD1.SD_AIN()
        AWGPart = self.dig.getProductNameBySlot(
            self.chassis, int(self.comCfg.address))
        self.log('Serial:', self.dig.getSerialNumberBySlot(
            self.chassis, int(self.comCfg.address)))
        if not isinstance(AWGPart, str):
            raise Error('Unit not available')
        # check that model is supported
        dOptionCfg = self.dInstrCfg['options']
        for validId, validName in zip(dOptionCfg['model_id'], dOptionCfg['model_str']):
            if AWGPart.find(validId)>=0:
                # id found, stop searching
                break
        else:
            # loop fell through, raise ID error
            raise IdError(AWGPart, dOptionCfg['model_id'])
        # set model
        self.setModel(validName)
        # sampling rate and number of channles is set by model
        if validName in ('M3102', 'M3302'):
            # 500 MHz models
            self.dt = 2E-9
            self.nCh = 4
        else:
            # assume 100 MHz for all other models
            self.dt = 10E-9
            self.nCh = 4
        # create list of sampled data
        self.lTrace = [np.array([])] * self.nCh
        self.dig.openWithSlot(AWGPart, self.chassis, int(self.comCfg.address))
        # get hardware version - changes numbering of channels
        hw_version = self.dig.getHardwareVersion()
        if hw_version >= 4:
            # KEYSIGHT - channel numbers start with 1
            self.ch_index_zero = 1
        else:
            # SIGNADYNE - channel numbers start with 0
            self.ch_index_zero = 0
        self.log('HW:', hw_version)


    def get_hw_ch(self, n):
        """Get hardware channel number for channel n. n starts at 0"""
        return n + self.ch_index_zero


    def performClose(self, bError=False, options={}):
        """Perform the close instrument connection operation"""
        # do not check for error if close was called with an error
        try:
            # flush all memory
            for n in range(self.nCh):
                self.log('Close ch:', n, self.dig.DAQflush(self.get_hw_ch(n)))
            # close instrument
            self.dig.close()
        except:
            # never return error here
            pass


    def performSetValue(self, quant, value, sweepRate=0.0, options={}):
        """Perform the Set Value instrument operation. This function should
        return the actual value set by the instrument"""
        # start with setting local quant value
        quant.setValue(value)
        # check if channel-specific, if so get channel + name
        if quant.name.startswith('Ch') and len(quant.name)>6:
            ch = int(quant.name[2]) - 1
            name = quant.name[6:]
        else:
            ch, name = None, ''
        # proceed depending on command
        if quant.name in ('External Trig Source', 'External Trig Config',
                          'Trig Sync Mode'):
            extSource = int(self.getCmdStringFromValue('External Trig Source'))
            trigBehavior = int(self.getCmdStringFromValue('External Trig Config'))
            sync = int(self.getCmdStringFromValue('Trig Sync Mode'))
            self.dig.DAQtriggerExternalConfig(0, extSource, trigBehavior, sync)
        elif quant.name in ('Trig I/O', ):
            # get direction and sync from index of comboboxes
            direction = int(self.getCmdStringFromValue('Trig I/O'))
            self.dig.triggerIOconfig(direction)
        elif quant.name in ('Analog Trig Channel', 'Analog Trig Config', 'Trig Threshold'):
            # get trig channel
            trigCh = self.getValueIndex('Analog Trig Channel')
            mod = int(self.getCmdStringFromValue('Analog Trig Config'))
            threshold = self.getValue('Trig Threshold')
            self.dig.channelTriggerConfig(self.get_hw_ch(trigCh), mod, threshold)
        elif name in ('Range', 'Impedance', 'Coupling'):
            # set range, impedance, coupling at once
            rang = self.getRange(ch)
            imp = int(self.getCmdStringFromValue('Ch%d - Impedance' % (ch + 1)))
            coup = int(self.getCmdStringFromValue('Ch%d - Coupling' % (ch + 1)))
            self.dig.channelInputConfig(self.get_hw_ch(ch), rang, imp, coup)
        return value

        
    def performGetValue(self, quant, options={}):
        """Perform the Set Value instrument operation. This function should
        return the actual value set by the instrument"""
        # check if channel-specific, if so get channel + name
        if quant.name.startswith('Ch') and len(quant.name)>6:
            ch = int(quant.name[2]) - 1
            name = quant.name[6:]
        else:
            ch, name = None, ''
        if name == 'Signal':
            # get traces if first call
            if self.isFirstCall(options):
                # don't arm if in hardware trig mode
                self.getTraces(bArm=(not self.isHardwareTrig(options)))
            # return correct data
            value = quant.getTraceDict(self.lTrace[ch], dt=self.dt)
        else:
            # for all others, return local value
            value = quant.getValue()
            
        return value


    def performArm(self, quant_names, options={}):
        """Perform the instrument arm operation"""
        # arm by calling get traces
        self.getTraces(bArm=True, bMeasure=False)


    def getTraces(self, bArm=True, bMeasure=True):
        """Get all active traces"""
        # test timing
#        import time
#        t0 = time.clock()
#        lT = []
        # find out which traces to get
        self.lTrace = [np.array([])] * self.nCh
        lCh = []
        iChMask = 0
        for n in range(self.nCh):
            if self.getValue('Ch%d - Enabled' % (n + 1)):
                lCh.append(n)
                iChMask += 2**n
        # get current settings
        nPts = int(self.getValue('Number of samples'))
        nSeg = int(self.getValue('Number of records'))
        nAv = int(self.getValue('Number of averages'))
        # trigger delay is in 1/sample rate
        nTrigDelay = int(self.getValue('Trig Delay')/self.dt)

        if bArm:
            # configure trigger for all active channels
            for nCh in lCh:
                # channel number depens on hardware version
                ch = self.get_hw_ch(nCh)
                # extra config for trig mode
                if self.getValue('Trig Mode') == 'Digital trigger':
                    extSource = int(self.getCmdStringFromValue('External Trig Source'))
                    trigBehavior = int(self.getCmdStringFromValue('External Trig Config'))
                    sync = int(self.getCmdStringFromValue('Trig Sync Mode'))
                    self.dig.DAQtriggerExternalConfig(ch, extSource, trigBehavior, sync)
                    self.dig.DAQdigitalTriggerConfig(ch, extSource, trigBehavior)
                elif self.getValue('Trig Mode') == 'Analog channel':
                    digitalTriggerMode= 0
                    digitalTriggerSource = 0
                    trigCh = self.getValueIndex('Analog Trig Channel')
                    analogTriggerMask = 2**trigCh
                    self.dig.DAQtriggerConfig(ch, digitalTriggerMode, digitalTriggerSource, analogTriggerMask)
                # config daq and trig mode
                trigMode = int(self.getCmdStringFromValue('Trig Mode'))
                self.dig.DAQconfig(ch, nPts, nSeg*nAv, nTrigDelay, trigMode)
            #
            # start acquiring data
            self.dig.DAQstartMultiple(iChMask)
#        lT.append('Start %.1f ms' % (1000*(time.clock()-t0)))
        #
        # return if not measure
        if not bMeasure:
            return
        # define number of cycles to read at a time
        nCycleTotal = nSeg*nAv
        # set cycles equal to number of records, else 100
        nCyclePerCall = nSeg if nSeg>1 else 100
        nCall = int(np.ceil(nCycleTotal/nCyclePerCall))
        lScale = [(self.getRange(ch)/self.bitRange) for ch in range(self.nCh)]
        for n in range(nCall):
            # number of cycles for this call, could be fewer for last call
            nCycle = min(nCyclePerCall, nCycleTotal-(n*nCyclePerCall))
            # capture traces one by one
            for nCh in lCh:
                # channel number depens on hardware version
                ch = self.get_hw_ch(nCh)
                data = self.DAQread(self.dig, ch, nPts*nCycle, int(self.timeout_ms/nCall))
                # average, if wanted
                scale = (self.getRange(nCh)/self.bitRange)
                if nAv > 1 and data.size>0:
                    nAvHere = nCycle/nSeg
                    data = data.reshape((int(nAvHere), nPts*nSeg)).mean(0)
                    # adjust scaling to account for summing averages
                    scale = lScale[nCh]*(nAvHere/nAv)
                else:
                    # use pre-calculated scaling
                    scale = lScale[nCh]
                # convert to voltage, add to total average
                if n==0:
                    self.lTrace[nCh] = data*scale
                else:
                    self.lTrace[nCh] += data*scale
#                lT.append('N: %d, Tot %.1f ms' % (n, 1000*(time.clock()-t0)))
#        # log timing info
#        self.log(': '.join(lT))


    def getRange(self, ch):
        """Get channel range, as voltage.  Index start at 0"""
        rang = float(self.getCmdStringFromValue('Ch%d - Range' % (ch + 1)))
        return rang
        

    def DAQread(self, dig, nDAQ, nPoints, timeOut):
        """Read data diretly to numpy array"""
        if dig._SD_Object__handle > 0:
            if nPoints > 0:
                data = (keysightSD1.c_short * nPoints)()
                nPointsOut = dig._SD_Object__core_dll.SD_AIN_DAQread(dig._SD_Object__handle, nDAQ, data, nPoints, timeOut)
                if nPointsOut > 0:
                    return np.frombuffer(data, dtype=np.int16, count=nPoints)
                else:
                    return np.array([], dtype=np.int16)
            else:
                return keysightSD1.SD_Error.INVALID_VALUE
        else:
            return keysightSD1.SD_Error.MODULE_NOT_OPENED


if __name__ == '__main__':
    pass
