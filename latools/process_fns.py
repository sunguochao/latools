import os
import re
import numpy as np
import warnings

from io import BytesIO
from scipy.stats import gaussian_kde
from scipy.optimize import curve_fit

from .helpers import Bunch, fastgrad, fastsmooth, findmins, bool_2_indices
from .stat_fns import gauss


# Functions to work with laser ablation signals

# Despiking functions
def noise_despike(sig, win=3, nlim=24., maxiter=4):
    """
    Apply standard deviation filter to remove anomalous values.

    Parameters
    ----------
    win : int
        The window used to calculate rolling statistics.
    nlim : float
        The number of standard deviations above the rolling
        mean above which data are considered outliers.

    Returns
    -------
    None
    """
    if win % 2 != 1:
        win += 1  # win must be odd

    kernel = np.ones(win) / win  # make convolution kernel
    over = np.ones(len(sig), dtype=bool)  # initialize bool array
    # pad edges to avoid edge-effects
    npad = int((win - 1) / 2)
    over[:npad] = False
    over[-npad:] = False
    # set up monitoring
    nloops = 0
    # do the despiking
    while any(over) and (nloops < maxiter):
        rmean = np.convolve(sig, kernel, 'valid')  # mean by convolution
        rstd = rmean**0.5  # std = sqrt(signal), because count statistics
        # identify where signal > mean + std * nlim (OR signa < mean - std * nlim)
        over[npad:-npad] = (sig[npad:-npad] > rmean + nlim * rstd)  # | (sig[npad:-npad] < rmean - nlim * rstd)
        # if any are over, replace them with mean of neighbours
        if any(over):
            # replace with values either side
            # sig[over] = sig[np.roll(over, -1) | np.roll(over, 1)].reshape((sum(over), 2)).mean(1)
            # replace with mean
            sig[npad:-npad][over[npad:-npad]] = rmean[over[npad:-npad]]
            nloops += 1
        # repeat until no more removed.
    return sig


def expdecay_despike(sig, expdecay_coef, tstep, maxiter=3, silent=True):
    """
    THERE'S SOMETHING WRONG WITH THIS FUNCTION. REMOVES TOO MUCH DATA!

    Apply exponential decay filter to remove unrealistically low values.

    Parameters
    ----------
    exponent : float
        Exponent used in filter
    tstep : float
        The time increment between data points.
    maxiter : int
        The maximum number of iterations to
        apply the filter

    Returns
    -------
    None
    """
    lo = np.ones(len(sig), dtype=bool)  # initialize bool array
    nloop = 0  # track number of iterations
    # do the despiking
    while any(lo) and (nloop <= maxiter):
        # find values that are lower than allowed by the washout
        # characteristics of the laser cell.
        lo = sig < np.roll(sig * np.exp(expdecay_coef * tstep), 1)
        if any(lo):
            prev = sig[np.roll(lo, -1)]
            sig[lo] = prev
            nloop += 1

    if nloop >= maxiter and not silent:
        raise warnings.warn(('\n***maxiter ({}) exceeded during expdecay_despike***\n\n'.format(maxiter) +
                             'This is probably because the expdecay_coef is too small.\n'))
    return sig


def read_data(data_file, dataformat, name_mode):
    with open(data_file) as f:
        lines = f.readlines()

    if 'meta_regex' in dataformat.keys():
        meta = Bunch()
        for k, v in dataformat['meta_regex'].items():
            out = re.search(v[-1], lines[int(k)]).groups()
            for i in np.arange(len(v[0])):
                meta[v[0][i]] = out[i]

    # sample name
    if name_mode == 'file_names':
        sample = os.path.basename(data_file).split('.')[0]
    elif name_mode == 'metadata_names':
        sample = meta['name']
    else:
        sample = 0

    # column and analyte names
    columns = np.array(lines[dataformat['column_id']['name_row']].strip().split(dataformat['column_id']['delimiter']))
    if 'pattern' in dataformat['column_id'].keys():
        pr = re.compile(dataformat['column_id']['pattern'])
        analytes = [pr.match(c).groups()[0] for c in columns if pr.match(c)]

    # do any required pre-formatting
    if 'preformat_replace' in dataformat.keys():
        with open(data_file) as f:
                fbuffer = f.read()
        for k, v in dataformat['preformat_replace'].items():
            fbuffer = re.sub(k, v, fbuffer)
        # dead data
        read_data = np.genfromtxt(BytesIO(fbuffer.encode()),
                                  **dataformat['genfromtext_args']).T
    else:
        # read data
        read_data = np.genfromtxt(data_file,
                                  **dataformat['genfromtext_args']).T

    # data dict
    dind = np.ones(read_data.shape[0], dtype=bool)
    dind[dataformat['column_id']['timecolumn']] = False

    data = Bunch()
    data['Time'] = read_data[dataformat['column_id']['timecolumn']]
    data['rawdata'] = Bunch(zip(analytes, read_data[dind]))
    data['total_counts'] = read_data[dind].sum(0)

    return sample, analytes, data, meta


def autorange(t, sig, gwin=7, win=30,
              on_mult=(1.5, 1.), off_mult=(1., 1.5)):
    """
    Automatically separates signal and background in an on/off data stream.

    Step 1: Thresholding
    The background signal is determined using a gaussian kernel density
    estimator (kde) of all the data. Under normal circumstances, this
    kde should find two distinct data distributions, corresponding to
    'signal' and 'background'. The minima between these two distributions
    is taken as a rough threshold to identify signal and background
    regions. Any point where the trace crosses this thrshold is identified
    as a 'transition'.

    Step 2: Transition Removal
    The width of the transition regions between signal and background are
    then determined, and the transitions are excluded from analysis. The
    width of the transitions is determined by fitting a gaussian to the
    smoothed first derivative of the analyte trace, and determining its
    width at a point where the gaussian intensity is at at `conf` time the
    gaussian maximum. These gaussians are fit to subsets of the data
    centered around the transitions regions determined in Step 1, +/- `win`
    data points. The peak is further isolated by finding the minima and
    maxima of a second derivative within this window, and the gaussian is
    fit to the isolated peak.

    Parameters
    ----------
    t : array-like
        Independent variable (usually time).
    sig : array-like
        Dependent signal, with distinctive 'on' and 'off' regions.
    gwin : int
        The window used for signal smoothing and calculationg of first
        derivative.
        Defaults to 7.
    win : int
        The width (c +/- win) of the transition data subsets.
        Defaults to 20.
    on_mult and off_mult : tuple, len=2
        Control the width of the excluded transition regions, which is defined
        relative to the peak full-width-half-maximum (FWHM) of the transition
        gradient. The region n * FHWM below the transition, and m * FWHM above
        the tranision will be excluded, where (n, m) are specified in `on_mult`
        and `off_mult`.
        `on_mult` and `off_mult` apply to the off-on and on-off transitions,
        respectively.
        Defaults to (1.5, 1) and (1, 1.5).

    Returns
    -------
    fbkg, fsig, ftrn, failed : tuple
        where fbkg, fsig and ftrn are boolean arrays the same length as sig,
        that are True where sig is background, signal and transition, respecively.
        failed contains a list of transition positions where gaussian fitting
        has failed.
    """

    failed = []

    bins = 50
    kde_x = np.linspace(sig.min(), sig.max(), bins)

    kde = gaussian_kde(sig)
    yd = kde.pdf(kde_x)
    mins = findmins(kde_x, yd)  # find minima in kde

    sigs = fastsmooth(sig, gwin)

    bkg = sigs < (mins[0])  # set background as lowest distribution
    # bkg[0] = True  # the first value must always be background

    # assign rough background and signal regions based on kde minima
    fbkg = bkg
    fsig = ~bkg

    # remove transitions by fitting a gaussian to the gradients of
    # each transition
    # 1. calculate the absolute gradient of the target trace.
    g = abs(fastgrad(sig, gwin))
    # 2. determine the approximate index of each transition
    zeros = bool_2_indices(fsig).flatten()

    for z in zeros:  # for each approximate transition
        # isolate the data around the transition
        if z - win < 0:
            lo = win
            hi = int(z + win)
        elif z + win > (len(sig) - 1):
            lo = int(z - win)
            hi = len(sig) - 1
        else:
            lo = int(z - win)
            hi = int(z + win)

        xs = t[lo:hi]
        ys = g[lo:hi]

        # determine type of transition (on/off)
        tp = sigs[hi] > sigs[lo]  # True if 'on' transition.

        # fit a gaussian to the first derivative of each
        # transition. Initial guess parameters:
        #   - A: maximum gradient in data
        #   - mu: c
        #   - width: 2 * time step
        # The 'sigma' parameter of curve_fit:
        # This weights the fit by distance from c - i.e. data closer
        # to c are more important in the fit than data further away
        # from c. This allows the function to fit the correct curve,
        # even if the data window has captured two independent
        # transitions (i.e. end of one ablation and start of next)
        # ablation are < win time steps apart).
        c = t[z]  # center of transition
        width = float(np.diff(t[:2]) * 2)  # initial width guess
        try:
            pg, _ = curve_fit(gauss, xs, ys,
                              p0=(np.nanmax(ys),
                                  c,
                                  width),
                              sigma=abs(xs - c) + .01)
            # get the x positions when the fitted gaussian is at 'conf' of
            # maximum
            # determine transition FWHM
            fwhm = 2 * pg[-1] * np.sqrt(2 * np.log(2))
            # apply on_mult or off_mult, as appropriate.
            if tp:
                lim = np.array([-fwhm, fwhm]) * on_mult + pg[1]
            else:
                lim = np.array([-fwhm, fwhm]) * off_mult + pg[1]

            fbkg[(t > lim[0]) & (t < lim[1])] = False
            fsig[(t > lim[0]) & (t < lim[1])] = False
        except:
            failed.append(c)
            pass

    ftrn = ~fbkg & ~fsig

    # if there are any failed transitions, apply mean transition width to them
    if len(failed) > 0:
        trns = bool_2_indices(ftrn)
        tr_mean = (trns[:, 1] - trns[:, 0]).mean()
        for f in failed:
            ind = (t >= f - tr_mean / 2) & (t <= f + tr_mean / 2)
            fsig[ind] = False
            fbkg[ind] = False
            ftrn[ind] = False

    return fbkg, fsig, ftrn, failed


# def rolling_mean_std(sig, win=3):
#     npad = int((win - 1) / 2)
#     sumkernel = np.ones(win)
#     kernel = sumkernel / win
#     mean = np.convolve(sig, kernel, 'same')
#     mean[:npad] = sig[:npad]
#     mean[-npad:] = sig[-npad:]
#     # calculate sqdiff
#     sqdiff = (sig - mean)**2
#     sumsqdiff = np.convolve(sqdiff, sumkernel, 'same')
#     std = np.sqrt(sumsqdiff / win)

#     return mean[5], sqdiff[4:7], sumsqdiff[5], std[5]

#     # print(np.convolve(a, sumkernel, 'valid'))


# if __name__ == '__main__':
#     a = np.random.normal(5, 1, 100)
#     a[30] = 10
#     print(rolling_mean_std(a))

#     print(np.convolve(np.ones(10), np.ones(3), 'same'))
#     asub = a[4:7]
#     print(asub)
#     masub = np.mean(asub)
#     sqdiff = (asub - masub)**2
#     sumsqdiff = np.sum(sqdiff)
#     std = np.sqrt(sumsqdiff / 3)
#     print(masub, sumsqdiff, std)
