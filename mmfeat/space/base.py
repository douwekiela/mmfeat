'''
Vector space model bases
'''

import os

import cPickle as pickle

import numpy as np

from scipy.stats import spearmanr

from .sim import cosine

class Space(object):
    def __init__(self, descrs):
        self.reportMissing = True
        if isinstance(descrs, str):
            self.space = pickle.load(open(descrs, 'rb'))
        elif isinstance(descrs, dict):
            self.space = descrs
        else:
            raise TypeError('Expecting file name or dictionary of descriptors')
    def __getitem__(self, key):
        return self.space[key]
    def __contains__(self, key):
        return key in self.space
    def keys(self):
        return self.space.keys()
    def sim(self, x, y):
        return cosine(self.space[x], self.space[y])
    def spearman(self, dataset):
        if not isinstance(dataset, list) \
                or len(dataset) == 0 \
                or len(dataset[0]) != 3 \
                or not isinstance(dataset[0][2], float):
            raise TypeError('Dataset is not of correct type, list of [str, str, float] triples expected.')
        gs_scores, sys_scores = [], []
        for one, two, gs_score in dataset:
            try:
                sys_score = self.sim(one, two)
                gs_scores.append(gs_score)
                sys_scores.append(sys_score)
            except KeyError:
                if self.reportMissing:
                    print('Warning: Missing pair %s-%s - skipping' % (one, two))
                continue
        return spearmanr(gs_scores, sys_scores)
    def neighbours(self, key, n=None):
        sims = []
        for other_key in self.space:
            if other_key == key: continue
            sims.append((other_key, self.sim(key, other_key)))

        if n is None:
            n = len(sims)

        return sorted(sims, key = lambda x: x[1], reverse=True)[:n]

class AggSpace(Space):
    def __init__(self, descrs, aggFunc='mean', caching=True):
        self.reportMissing = True
        self.caching = caching
        self.cached_file_name = None

        if isinstance(descrs, str):
            self.descrs_file = descrs
            self.descrs = pickle.load(open(self.descrs_file, 'rb'))
            self.cached_file_name = '%s-%s.pkl' % (self.descrs_file, aggFunc)
        elif isinstance(descrs, dict):
            self.descrs = descrs

        if self.caching and self.cached_file_name is not None and os.path.exists(self.cached_file_name):
            self.space = pickle.load(open(self.cached_file_name, 'rb'))
        elif aggFunc in ['mean', 'median', 'max']:
            if aggFunc == 'mean':
                f = self.aggMean
            elif aggFunc == 'median':
                f = self.aggMedian
            elif aggFunc == 'max':
                f = self.aggMax

            self.space = {}
            for k in self.descrs.keys():
                vecs = self.descrs[k].values()
                if len(vecs) == 0:
                    if self.reportMissing:
                        print('Warning: Not enough vectors for key %s - skipping' % k)
                    continue
                if len(vecs) == 1:
                    self.space[k] = vecs[0]
                else:
                    self.space[k] = f(vecs)

            if self.caching and self.cached_file_name is not None:
                pickle.dump(self.space, open(self.cached_file_name, 'wb'))

    def aggMean(self, m):
        return np.mean(np.nan_to_num(m), axis=0, dtype=np.float64)
    def aggMedian(self, m):
        return np.median(np.nan_to_num(m), axis=0)
    def aggMax(self, m):
        return np.max(np.nan_to_num(m), axis=0)

    def getDispersions(self, rescale=True, n_images=None):
        self.cached_dispersions_file = None
        if self.caching and hasattr(self, 'descrs_file'):
            self.cached_dispersions_file = '%s-dispersions.pkl' % (self.descrs_file)
            if os.path.exists(self.cached_dispersions_file):
                self.dispersions = pickle.load(open(self.cached_dispersions_file, 'rb'))
                return

        def disp(M):
            l = len(M)
            d, cnt = 0, 0
            for i in range(l):
                for j in range(i) + range(i+1, l):
                    d += (1 - cosine(M[i], M[j]))
                    cnt += 1
            return d / cnt if cnt != 0 else 0

        self.dispersions = {}
        min_disp, max_disp = 1, 0
        for k in self.descrs:
            image_reps = self.descrs[k].values()
            if n_images is not None:
                image_reps = image_reps[:n_images]

            imgdisp = disp(image_reps)

            self.dispersions[k] = imgdisp
            if imgdisp > max_disp:
                max_disp, max_key = imgdisp, k
            if imgdisp < min_disp:
                min_disp, min_key = imgdisp, k

        # rescale
        if rescale:
            for k in self.dispersions:
                self.dispersions[k] = max(0, min(1, (self.dispersions[k] - min_disp) / (max_disp - min_disp)))

        if self.caching and self.cached_dispersions_file is not None:
            pickle.dump(self.dispersions, open(self.cached_dispersions_file, 'wb'))


    def nearest_neighbours(self, key, n=None):
        '''Return the nearest neighbours to the centroid.'''
        sims = []
        for k, v in self.descrs[key].items():
            sims.append(((k, v), cosine(v, self.space[key])))

        if n is None:
            n = len(sims)

        return dict(map(lambda s: s[0], sorted(sims, key = lambda x: x[1], reverse=True)[:n]))

    def filter_nearest_neighbours(self, n):
        '''Filter nearest neighbours and only aggregate these.'''
        for k in self.descrs:
            self.descrs[k] = self.nearest_neighbours(k, n)

    def update_space(self, aggFunc='mean', caching=True):
        self.__init__(self.descrs, aggFunc=aggFunc, caching=caching)
