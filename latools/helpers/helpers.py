"""
Helper functions used by multiple parts of LAtools.

(c) Oscar Branson : https://github.com/oscarbranson
"""
import os
import shutil
import re
import configparser
import datetime as dt
import numpy as np
import dateutil as du
import pkg_resources as pkgrs
import uncertainties.unumpy as un
import scipy.interpolate as interp
from .stat_fns import nominal_values
from .analyte_names import pretty_element

# Bunch modifies dict to allow item access using dot (.) operator
class Bunch(dict):
    def __init__(self, *args, **kwds):
        super(Bunch, self).__init__(*args, **kwds)
        self.__dict__ = self

# warnings monkeypatch
# https://stackoverflow.com/questions/2187269/python-print-only-the-message-on-warnings
def _warning(message, category=UserWarning,
             filename='', lineno=-1,
             file=None, line=None):
    print(message)

def get_date(datetime, time_format=None):
    """
    Return a datetime oject from a string, with optional time format.

    Parameters
    ----------
    datetime : str
        Date-time as string in any sensible format.
    time_format : datetime str (optional)
        String describing the datetime format. If missing uses
        dateutil.parser to guess time format.
    """
    if time_format is None:
        t = du.parser.parse(datetime)
    else:
        t = dt.datetime.strptime(datetime, time_format)
    return t

def get_total_n_points(d):
    """
    Returns the total number of data points in values of dict.

    Paramters
    ---------
    d : dict
    """
    n = 0
    for di in d.values():
        n += len(di)
    return n

def get_total_time_span(d):
    """
    Returns total length of analysis.
    """

    tmax = 0
    for di in d.values():
        if di.uTime.max() > tmax:
            tmax = di.uTime.max()
    
    return tmax

def unitpicker(a, denominator=None, focus_stage=None):
    """
    Determines the most appropriate plotting unit for data.

    Parameters
    ----------
    a : float or array-like
        number to optimise. If array like, the 25% quantile is optimised.
    llim : float
        minimum allowable value in scaled data.

    Returns
    -------
    (float, str)
        (multiplier, unit)
    """

    if not isinstance(a, (int, float)):
        a = nominal_values(a)
        a = np.percentile(a[~np.isnan(a)], 25)

    if a == 0:
        raise ValueError("Cannot calculate unit for zero.")

    if denominator is not None:
        pd = pretty_element(denominator)
    else:
        pd = ''

    if focus_stage == 'calibrated':
        udict = {0: 'mol/mol ' + pd,
                 3: 'mmol/mol ' + pd,
                 6: '$\mu$mol/mol ' + pd,
                 9: 'nmol/mol ' + pd,
                 12: 'pmol/mol ' + pd,
                 15: 'fmol/mol ' + pd}
    elif focus_stage == 'ratios':
        udict = {0: 'counts/count ' + pd,
                 3: '$10^{-3}$ counts/count ' + pd,
                 6: '$10^{-6}$ counts/count ' + pd,
                 9: '$10^{-9}$ counts/count ' + pd,
                 12: '$10^{-12}$ counts/count ' + pd,
                 15: '$10^{-15}$ counts/count ' + pd}
    elif focus_stage in ('rawdata', 'despiked', 'bkgsub'):
        udict = udict = {0: 'counts',
                         3: '$10^{-3}$ counts',
                         6: '$10^{-6}$ counts',
                         9: '$10^{-9}$ counts',
                         12: '$10^{-12}$ counts',
                         15: '$10^{-15}$ counts'}
    else:
        udict = {0: '', 3: '', 6: '', 9: '', 12: '', 15: ''}

    a = abs(a)
    order = np.log10(a)
    m = np.ceil(-order / 3) * 3
    return float(10**m), udict[m]

def collate_data(in_dir, extension='.csv', out_dir=None):
    """
    Copy all csvs in nested directroy to single directory.

    Function to copy all csvs from a directory, and place
    them in a new directory.

    Parameters
    ----------
    in_dir : str
        Input directory containing csv files in subfolders
    extension : str
        The extension that identifies your data files.
        Defaults to '.csv'.
    out_dir : str
        Destination directory

    Returns
    -------
    None
    """
    if out_dir is None:
        out_dir = './' + re.search('^\.(.*)', extension).groups(0)[0]

    if not os.path.isdir(out_dir):
        os.mkdir(out_dir)

    for p, d, fs in os.walk(in_dir):
        for f in fs:
            if extension in f:
                shutil.copy(p + '/' + f, out_dir + '/' + f)
    return

def bool_transitions(a):
    """
    Return indices where a boolean array changes from True to False
    """
    return np.where(a[:-1] != a[1:])[0]

def bool_2_indices(a):
    """
    Convert boolean array into a 2D array of (start, stop) pairs.
    """
    if any(a):
        lims = []
        lims.append(np.where(a[:-1] != a[1:])[0])

        if a[0]:
            lims.append([0])
        if a[-1]:
            lims.append([len(a) - 1])
        lims = np.concatenate(lims)
        lims.sort()

        return np.reshape(lims, (lims.size // 2, 2))
    else:
        return None

def enumerate_bool(bool_array, nstart=0):
    """
    Consecutively numbers contiguous booleans in array.

    i.e. a boolean sequence, and resulting numbering
    T F T T T F T F F F T T F
    0-1 1 1 - 2 ---3 3 -

    where ' - '

    Parameters
    ----------
    bool_array : array_like
        Array of booleans.
    nstart : int
        The number of the first boolean group.
    """
    ind = bool_2_indices(bool_array)
    ns = np.full(bool_array.size, nstart, dtype=int)
    for n, lims in enumerate(ind):
        ns[lims[0]:lims[-1] + 1] = nstart + n + 1
    return ns

def tuples_2_bool(tuples, x):
    """
    Generate boolean array from list of limit tuples.

    Parameters
    ----------
    tuples : array_like
        [2, n] array of (start, end) values
    x : array_like
        x scale the tuples are mapped to

    Returns
    -------
    array_like
        boolean array, True where x is between each pair of tuples.
    """
    if np.ndim(tuples) == 1:
        tuples = [tuples]

    out = np.zeros(x.size, dtype=bool)
    for l, u in tuples:
        out[(x > l) & (x < u)] = True
    return out

def get_example_data(destination_dir):
    if os.path.isdir(destination_dir):
        overwrite = input(destination_dir +
                          ' already exists. Overwrite? [N/y]: ').lower() == 'y'
        if overwrite:
            shutil.rmtree(destination_dir)
        else:
            print(destination_dir + ' was not overwritten.')

    shutil.copytree(pkgrs.resource_filename('latools', 'resources/test_data'),
                    destination_dir)

    return

def rangecalc(xs, pad=0.05):
    mn = np.nanmin(xs)
    mx = np.nanmax(xs)
    xr = mx - mn
    return [mn - pad * xr, mx + pad * xr]

class un_interp1d(object):
    """
    object for handling interpolation of values with uncertainties.
    """

    def __init__(self, x, y, fill_value=np.nan, **kwargs):
        if isinstance(fill_value, tuple):
            nom_fill = tuple([un.nominal_values(v) for v in fill_value])
            std_fill = tuple([un.std_devs(v) for v in fill_value])
        else:
            nom_fill = std_fill = fill_value
        self.nom_interp = interp.interp1d(un.nominal_values(x),
                                          un.nominal_values(y),
                                          fill_value=nom_fill, **kwargs)
        self.std_interp = interp.interp1d(un.nominal_values(x),
                                          un.std_devs(y),
                                          fill_value=std_fill, **kwargs)

    def new(self, xn):
        yn = self.nom_interp(xn)
        yn_err = self.std_interp(xn)
        return un.uarray(yn, yn_err)

    def new_nom(self, xn):
        return self.nom_interp(xn)

    def new_std(self, xn):
        return self.std_interp(xn)

def rolling_window(a, window, window_mode='mid', pad=None):
    """
    Returns (win, len(a)) rolling - window array of data.

    Parameters
    ----------
    a : array_like
        Array to calculate the rolling window of
    window : int
        Description of `window`.
    window_mode : str
        Describes the jusitification of the rolling window relative to the
        returned values. Can be 'left', 'mid' or 'right'.
    pad : same as dtype(a)
        How to pad the ends of the array such that shape[0] of the returned array
        is the same as len(a). Can be 'ends', 'mean_ends' or 'repeat_ends'. 'ends'
        just extends the start or end value across all the extra windows. 'mean_ends'
        extends the mean value of the end windows. 'repeat_ends' repeats the end window
        to completion.

    Returns
    -------
    array_like
        An array of shape (n, window), where n is either len(a) - window
        if pad is None, or len(a) if pad is not None.
    """
    shape = a.shape[:-1] + (a.shape[-1] - window + 1, window)
    strides = a.strides + (a.strides[-1], )
    out = np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides)
    # pad shape
    if window_mode == 'mid':
        if window % 2 == 0:    
            npre = window // 2 - 1
            npost = window // 2
        else:
            npre = npost = window // 2
    elif window_mode == 'right':
        npre = window - 1
        npost = 0
    elif window_mode == 'left':
        npre = 0
        npost = window - 1
    else:
        raise ValueError("`window_mode` must be 'left', 'mid' or 'right'.")

    if isinstance(pad, str):
        if pad == 'ends':
            prepad = np.full((npre, window), a[0])
            postpad = np.full((npost, window), a[-1])
        elif pad == 'mean_ends':
            prepad = np.full((npre, window), np.mean(a[:(window // 2)]))
            postpad = np.full((npost, window), np.mean(a[-(window // 2):]))
        elif pad == 'repeat_ends':
            prepad = np.full((npre, window), out[0])
            postpad = np.full((npost, window), out[-1])
        else:
            raise ValueError("`pad` must be either 'ends', 'mean_ends' or 'repeat_ends'.")
        return np.concatenate((prepad, out, postpad))
    elif pad is not None:
        pre_blankpad = np.empty(((npre, window)))
        pre_blankpad[:] = pad
        post_blankpad = np.empty(((npost, window)))
        post_blankpad[:] = pad
        return np.concatenate([pre_blankpad, out, post_blankpad])
    else:
        return out

def fastsmooth(a, win=11):
    """
    Returns rolling - window smooth of a.

    Function to efficiently calculate the rolling mean of a numpy
    array using 'stride_tricks' to split up a 1D array into an ndarray of
    sub - sections of the original array, of dimensions [len(a) - win, win].

    Parameters
    ----------
    a : array_like
        The 1D array to calculate the rolling gradient of.
    win : int
        The width of the rolling window.

    Returns
    -------
    array_like
        Gradient of a, assuming as constant integer x - scale.
    """
    # check to see if 'window' is odd (even does not work)
    if win % 2 == 0:
        win += 1  # add 1 to window if it is even.
    kernel = np.ones(win) / win
    npad = int((win - 1) / 2)
    spad = np.full(npad + 1, np.mean(a[:(npad + 1)]))
    epad = np.full(npad - 1, np.mean(a[-(npad - 1):]))
    return np.concatenate([spad, np.convolve(a, kernel, 'valid'), epad])

def fastgrad(a, win=11, win_mode='mid'):
    """
    Returns rolling - window gradient of a.

    Function to efficiently calculate the rolling gradient of a numpy
    array using 'stride_tricks' to split up a 1D array into an ndarray of
    sub - sections of the original array, of dimensions [len(a) - win, win].

    Parameters
    ----------
    a : array_like
        The 1D array to calculate the rolling gradient of.
    win : int
        The width of the rolling window.
    win_mode : str
        Describes the jusitification of the rolling window relative to the
        returned values. Can be 'left', 'mid' or 'right'.

    Returns
    -------
    array_like
        Gradient of a, assuming as constant integer x - scale.
    """
    # check to see if 'window' is odd (even does not work)
    if win % 2 == 0:
        win += 1  # add 1 to window if it is even.
    # trick for efficient 'rolling' computation in numpy
    # shape = a.shape[:-1] + (a.shape[-1] - win + 1, win)
    # strides = a.strides + (a.strides[-1], )
    # wins = np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides)
    wins = rolling_window(a, win, pad='ends', window_mode=win_mode)
    # apply rolling gradient to data
    a = map(lambda x: np.polyfit(np.arange(win), x, 1)[0], wins)

    return np.array(list(a))

def calc_grads(x, dat, keys=None, win=5, win_mode='mid'):
    """
    Calculate gradients of values in dat.
    
    Parameters
    ----------
    x : array like
        Independent variable for items in dat.
    dat : dict
        {key: dependent_variable} pairs
    keys : str or array-like
        Which keys in dict to calculate the gradient of.
    win : int
        The side of the rolling window for gradient calculation
    win_mode : str
        Describes the jusitification of the rolling window relative to the
        returned values. Can be 'left', 'mid' or 'right'.

    Returns
    -------
    dict of gradients
    """
    if keys is None:
        keys = dat.keys()

    def grad(xy):
        idx = np.isfinite(xy[1])
        if sum(idx) > 2:
            try:
                return np.polyfit(xy[0][idx], xy[1][idx], 1)[0]
            except ValueError:
                return np.nan
        else:
            return np.nan

    xs = rolling_window(x, win, pad='repeat_ends', window_mode=win_mode)

    grads = Bunch()
    for k in keys:
        d = nominal_values(rolling_window(dat[k], win, pad='repeat_ends', window_mode=win_mode))

        grads[k] = np.array(list(map(grad, zip(xs, d))))

    return grads

def findmins(x, y):
    """ Function to find local minima.

    Parameters
    ----------
    x, y : array_like
        1D arrays of the independent (x) and dependent (y) variables.

    Returns
    -------
    array_like
        Array of points in x where y has a local minimum.
    """
    return x[np.r_[False, y[1:] < y[:-1]] & np.r_[y[:-1] < y[1:], False]]

def stack_keys(ddict, keys, extra=None):
    """
    Combine elements of ddict into an array of shape (len(ddict[key]), len(keys)).

    Useful for preparing data for sklearn.

    Parameters
    ----------
    ddict : dict
        A dict containing arrays or lists to be stacked.
        Must be of equal length.
    keys : list or str
        The keys of dict to stack. Must be present in ddict.
    extra : list (optional)
        A list of additional arrays to stack. Elements of extra
        must be the same length as arrays in ddict.
        Extras are inserted as the first columns of output.
    """
    if isinstance(keys, str):
        d = [ddict[keys]]
    else:
        d = [ddict[k] for k in keys]
    if extra is not None:
        d = extra + d
    return np.vstack(d).T

def analyte_checker(self, analytes=None, check_ratios=True, single=False):
    """
    Return valid analytes depending on the analysis stage
    """
    if isinstance(analytes, str):
        analytes = [analytes]

    out = set()
    if self.focus_stage not in ['ratios', 'calibrated'] or not check_ratios:
        if analytes is None:
            analytes = self.analytes
        out = self.analytes.intersection(analytes)
    else:
        if analytes is None:
            analytes = self.analyte_ratios
        # case 1: provided analytes are an exact match for items in analyte_ratios
        valid1 = self.analyte_ratios.intersection(analytes)
        # case 2: provided analytes are in numerator of ratios
        valid2 = [a for a in self.analyte_ratios if a.split('_')[0] in analytes]
        out = valid1.union(valid2)
    
    if len(out) == 0:
        raise ValueError(f'{analytes} does not match any valid analyte names.')

    if single:
        if len(out) > 1:
            raise ValueError(f'{analytes} matches more than one valid analyte ({out}). Please be more specific.')
        return out.pop()

    return out