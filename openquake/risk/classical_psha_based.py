# -*- coding: utf-8 -*-
"""
This module defines the functions used to compute loss ratio curves
using the classical psha based approach.
"""

from numpy import linspace # pylint: disable=F0401,E0611
import scipy # pylint: disable=F0401

from numpy import empty # pylint: disable=F0401,E0611
from numpy import isnan # pylint: disable=F0401,E0611
from scipy import sqrt # pylint: disable=F0401,E0611
from scipy import stats # pylint: disable=F0401,E0611
from scipy import log # pylint: disable=F0401,E0611

from openquake import shapes

STEPS_PER_INTERVAL = 5


def compute_loss_ratio_curve(vuln_function, hazard_curve):
    """Compute a loss ratio curve for a specific hazard curve (e.g., site),
    by applying a given vulnerability function.

    A loss ratio curve is a function that has loss ratios as X values
    and PoEs (Probabilities of Exceendance) as Y values.
    """

    if vuln_function is None:
        vuln_function = shapes.EMPTY_VULN_FUNCTION

    lrem = _compute_lrem(vuln_function)
    lrem_po = _compute_lrem_po(vuln_function, lrem, hazard_curve)
    loss_ratios = _generate_loss_ratios(vuln_function)
    loss_ratio_curve = _compute_loss_ratio_curve_from_lrem_po(
                            loss_ratios, lrem_po)

    return loss_ratio_curve


def _compute_lrem_po(vuln_function, lrem, hazard_curve):
    """Compute the LREM * PoOs matrix.""" 

    lrem_po = empty((len(lrem), len(vuln_function.imls)), float)

    for idx, value in enumerate(vuln_function):
        prob_occ = hazard_curve.ordinate_for(value[0])

        for row in range(len(lrem_po)):
            lrem_po[row][idx] = lrem[row][idx] * prob_occ

    return lrem_po


def _compute_loss_ratio_curve_from_lrem_po(loss_ratios, lrem_po):
    """Compute the final loss ratio curve."""
    return shapes.Curve(zip(loss_ratios, lrem_po.sum(axis=1)[:-1]))


def _generate_loss_ratios(vuln_function):
    """Loss ratios are a function of the vulnerability curve."""
    loss_ratios = list(vuln_function.means)
    loss_ratios.insert(0, 0.0)
    return _split_loss_ratios(loss_ratios)


def _compute_lrem(vuln_function, distribution=None):
    """Compute the LREM (Loss Ratio Exceedance Matrix)."""

    if not distribution:
        distribution = stats.lognorm
        # this is so we can memoize the thing

    loss_ratios = _generate_loss_ratios(vuln_function)
    loss_ratios.append(1.0) # last loss ratio is fixed to be 1
    lrem = empty((len(loss_ratios), len(vuln_function.imls)), float)

    def fix_prob(prob):
        """Fix probabilities for values close to zero."""
        if isnan(prob):
            return 0.0
        if prob < 0.00001: 
            return 0.0
        else: 
            return prob

    for idx, value in enumerate(vuln_function):
        iml, mean, cov = value
        stddev = cov * mean
        variance = stddev ** 2.0
        mu = log(mean ** 2.0 / sqrt(variance + mean ** 2.0) )
        sigma = sqrt(log((variance / mean ** 2.0) + 1.0))
        
        for row in range(len(lrem)):
            lrem[row][idx] = fix_prob(
                    distribution.sf(loss_ratios[row],
                    sigma, scale=scipy.exp(mu)))
    
    return lrem


def _split_loss_ratios(loss_ratios, steps=STEPS_PER_INTERVAL):
    """Split the loss ratios.

    steps is the number of steps we make to go from one loss
    ratio to the other. For example, if we have [1.0, 2.0]:

        steps = 1 produces [1.0, 2.0]
        steps = 2 produces [1.0, 1.5, 2.0]
        steps = 3 produces [1.0, 1.33, 1.66, 2.0]
    """

    splitted_ratios = set()
    for idx in range(len(loss_ratios) - 1):
        splitted_ratios.update(
                linspace(loss_ratios[idx],
                loss_ratios[idx + 1], steps + 1))

    return list(sorted(splitted_ratios))
