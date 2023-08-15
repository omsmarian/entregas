import sympy as sym
import scipy.signal as signal
from scipy.optimize import basinhopping
import numpy as np
from numpy.polynomial import Polynomial
from .Parser import ExprParser
import traceback

# Evaluate a polynomial in reverse order using Horner's Rule,
# for example: a3*x^3+a2*x^2+a1*x+a0 = ((a3*x+a2)x+a1)x+a0
def poly_at(p, x):
    total = 0
    for a in p:
        total = total * x + a
    return total

class TFunction():
    def __init__(self, *args, normalize=False):
        self.tf_object = {}
        self.eparser = ExprParser()

        self.p = []
        self.z = []
        self.k = 1
        self.N = []
        self.D = []
        self.dN = []
        self.dD = []

        if(len(args) == 1):
            self.setExpression(args[0], normalize=normalize)
        if(len(args) == 2):
            self.setND(args[0], args[1], normalize=normalize)
        if(len(args) == 3):
            self.setZPK(args[0], args[1], args[2], normalize=normalize)

    def setExpression(self, txt, normalize=False):
        try:
            self.eparser.setTxt(txt)
            N, D = self.eparser.getND()
            self.setND(N, D, normalize=normalize)
            return True
        except:
            return False

    def setND(self, N, D, normalize=False):
        if not hasattr(N, '__iter__'):
            N = [N]
        if not hasattr(D, '__iter__'):
            D = [D]
        self.N, self.D = np.array(N, dtype=np.float64), np.array(D, dtype=np.float64)
        self.z, self.p, self.k = signal.tf2zpk(self.N, self.D)        
        if normalize:
            self.normalize()
        self.tf_object = signal.TransferFunction(self.N, self.D)
        self.computedDerivatives = False
    
    def getND(self):
        return self.N, self.D

    #Nota: signal NO normaliza la transferencia, por lo que k multiplica pero no es la ganancia en s=0
    def setZPK(self, z, p, k, normalize=False):
        self.z, self.p, self.k = np.array(z, dtype=np.complex128), np.array(p, dtype=np.complex128), self.k
        self.k = k
        N, D = signal.zpk2tf(self.z, self.p, self.k)
        if not hasattr(N, '__iter__'):
            N = [N]
        if not hasattr(D, '__iter__'):
            D = [D]
        self.N, self.D = np.array(N, dtype=np.float64), np.array(D, dtype=np.float64)
        if normalize:
            self.normalize()
        self.computedDerivatives = False
        self.tf_object = signal.ZerosPolesGain(self.z, self.p, self.k)

    def getZPK(self, in_hz=False):
        if(in_hz):
            return self.z/(2*np.pi), self.p/(2*np.pi), self.k
        else:
            return self.z, self.p, self.k

    def getDerivatives(self):
        N = Polynomial(np.flip(self.N))
        D = Polynomial(np.flip(self.D))
        self.dN = np.flip(N.deriv().coef)
        self.dD = np.flip(D.deriv().coef)
        self.computedDerivatives = True

    def normalize(self):
        a = 1 #lo voy a usar para normalizar, los zpk que da numpy no vienen normalizados
        for zero in self.z:
            a *= -zero
        for pole in self.p:
            a /= -pole
        self.k = self.k/a
        self.N = self.N/a
        self.computedDerivatives = False
    
    def denormalize(self):
        a = 1
        for zero in self.z:
            a *= -zero
        for pole in self.p:
            a /= -pole
        self.k = self.k*a
        self.N = self.N*a
        self.computedDerivatives = False

    def at(self, s):
        return poly_at(self.N, s) / poly_at(self.D, s)
    
    def minFunctionMod(self, w):
        return abs(self.at(1j*w))
    
    def maxFunctionMod(self, w):
        return -abs(self.at(1j*w))
    
    #como ln(H) = ln(G) + j phi --> H'/H = G'/G + j phi'
    def gd_at(self, w0):
        if not self.computedDerivatives:
            self.getDerivatives()
        return -np.imag(1j*(poly_at(self.dN, 1j*w0)/poly_at(self.N, 1j*w0) - poly_at(self.dD, 1j*w0)/poly_at(self.D, 1j*w0))) #'1j*..' --> regla de la cadena
        
    def getZP(self, in_hz=False):
        if(in_hz):
            return self.z/(2*np.pi), self.p/(2*np.pi)
        else:
            return self.z, self.p

    def getBode(self, linear=False, start=-2, stop=6, num=10000):
        if linear:
            ws = np.linspace(start, stop, num) * 2 * np.pi
        else:
            ws = np.logspace(start, stop, num) * 2 * np.pi
        #h = self.at(1j*ws)
        w, g, ph = signal.bode(self.tf_object, w=ws)
        gd = self.gd_at(ws) #/ (2 * np.pi) #--> no hay que hacer regla de cadena porque se achica tmb la escala de w
        f = ws / (2 * np.pi)
        return f, 10**(g/20), ph, gd

    #No funciona (y no lo necesitamos) actualmente
    def optimize(self, start, stop, maximize = False):
        # rewrite the bounds in the way required by L-BFGS-B
        bounds = [(start, stop)]
        w0 = 0.5*(start + stop)

        if not maximize:
            f = lambda w : self.minFunctionMod(w)
        else:
            f = lambda w : self.maxFunctionMod(w)

        # use method L-BFGS-B because the problem is smooth and bounded
        minimizer_kwargs = dict(method="L-BFGS-B", bounds=bounds)
        res = basinhopping(f, w0, minimizer_kwargs=minimizer_kwargs)
        return res.x, (res.fun if not maximize else -res.fun)

    def appendStage(self, tf):
        self.setZPK(np.append(self.z, tf.z), np.append(self.p, tf.p), self.k*tf.k)

    def removeStage(self, tf):
        self.setZPK([i for i in self.z if i not in tf.z], [i for i in self.p if i not in tf.p], self.k/tf.k)
        
    def getLatex(self, txt):
        return self.eparser.getLatex()