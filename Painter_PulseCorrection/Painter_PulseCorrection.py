import sys
sys.path.append('C:\\Program Files (x86)\\Labber\\Script')
import Labber
import numpy as np
from scipy.interpolate import interp1d
import InstrumentDriver

class Driver(InstrumentDriver.InstrumentWorker):
    """This class implements PulseCorrection."""
    ndict = {'One': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5, 'Six': 6,
             'Seven': 7, 'Eight': 8, 'Nine': 9}

    def performOpen(self, options={}):
        """Perform the operation of opening the instrument connection"""
        self.is_uniform_transfer_func = self.getValue("Uniform Transfer Function")
        self.nTraces = ndict[self.getValue('Number of Traces to Correct')]

        # store list of input traces
        self.input_traces = []
        for n in range(self.nTraces):
            trace_in = self.getValue("Input Trace #" + str(n + 1))
            self.input_traces.append(trace_in)

        # store list of transfer functions
        self.transfer_funcs = []
        if self.is_uniform_transfer_func:
            dpath = self.getValue('Transfer Function - Path')
            self.transfer_funcs.append(__transfer_func(dpath))
        else:
            for n in range(self.nTraces):
                dpath = self.getValue('Transfer Function - Path #' + str(n + 1))
                self.transfer_funcs.append(__transfer_func(dpath))

    def __append_balancing_pulse(self, trace_idx):

    def __transfer_func(path):
        """
        Construct transfer function from interpolation of data specified by path
        """
        f = Labber.LogFile(path)
        d = f.getEntry(0)

        vFreq = d['Frequency']
        vH = d['Signal - Real'] + 1j * d['Signal - Imag']
        return interp1d(2 * np.pi * vFreq, vH)

    def performSetValue(self, quant, value, sweepRate=0.0, options={}):
        """Perform the Set Value instrument operation."""
        return value

    def performGetValue(self, quant, options={}):
        """Perform the Get Value instrument operation."""
        value = quant.getValue()

        if quant.name.startswith('Input Trace'):
            n = int(quant.name.split(' #')[1]) - 1
            value = self.getValue("Input Trace #" + str(n + 1))
            self.log("Trace In #" + str(n + 1) + " = " + str(value['y']))
            self.input_traces[n] = value

            # TODO: balancing pulse

        if quant.name.startswith('Output Trace'):
            n = int(quant.name.split(' #')[1]) - 1

            H = self.transfer_funcs[0]
            if not self.is_uniform_transfer_func:
                # if not using uniform transfer function, overwrite the function
                H = self.transfer_funcs[n]

            trace_in = self.input_traces[n]
            y_in = trace_in['y']
            dt_in = trace_in['dt']
            t_in = np.array([trace_in['t0'] + m * dt_in for m in range(len(trace_in['y'])))

            # perform deconvolution of the trace if the vector has at least 2 entries
            if len(y_in) > 1:
                Y_in = np.fft.rfft(y_in, norm='ortho')
                ω = 2 * np.pi * np.fft.rfftfreq(y_in, d=dt_in)

                # deconvolution
                Y_out = Y_in / H
                y_out = np.fft.irfft(Y_out, norm='ortho')

                self.log("Trace Out #" + str(n + 1) + " = " + str(y_out))
                value = quant.getTraceDict(y_out, t0=t_in[0], dt=dt_in)
        return value

if __name__ == '__main__':
    pass
