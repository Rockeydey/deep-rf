import numpy as np
import multiprocessing

from itertools import chain


class XOfNAttribute(object):
    __slots__ = ('idx_attr', 'thresh_val', 'split_val', 'cost')
    """
    Parameters
    ----------
    idx_attr: int or list of ints, optional
        Indices of attributes that make up the X-of-N attribute. If None, initializes an empty attribute
        
    thresh_val: float or list of floats, optional
        Threshold values, corresponding to attribute indices. If None, initializes an empty attribute
        
    split_val: int or float
        Split point when using attribute to split a data set
        
    cost: int or float
        Complexity of attribute
    """
    def __init__(self, idx_attr=None, thresh_val=None, split_val=None, cost=None):
        self.idx_attr = idx_attr if idx_attr is not None else []
        self.thresh_val = thresh_val if thresh_val is not None else []
        self.split_val = split_val
        self.cost = cost

        if not isinstance(self.idx_attr, list):
            self.idx_attr = [self.idx_attr]

        if not isinstance(self.thresh_val, list):
            self.thresh_val = [self.thresh_val]

    def __len__(self):
        return len(self.idx_attr)

    def __str__(self):
        return "XoN(%s, split_val=%d)" \
               % (",".join([str(val) for val in zip(self.idx_attr, self.thresh_val)]), self.split_val)


def _find_valid_values(feat_subset, target):
    """ Narrows the search space of thresholds to be considered when finding the best one to split a data set. Returns
    threshold values from `feat_subset` that result in a class change (in `target`).

    Parameters
    ----------
    feat_subset: np.array
        Single column of a data set (i.e. values of current attribute for the entire data set)

    target: np.array
        Labels corresponding to `feat_subset`

    Returns
    -------
    np.array:
        "valid" thresholds
    """
    if feat_subset.shape[0] < 2:
        return feat_subset

    sort_idx = np.argsort(feat_subset)
    _feats = feat_subset[sort_idx]
    _target = target[sort_idx]
    valid = [_feats[0]]

    for i in range(1, _feats.shape[0]):
        if _target[i] != _target[i - 1] and _feats[i] != valid[-1]:
            valid.append(_feats[i])

    return np.array(valid)


def _fib(n):
    """ Computes Fibonacci's number F(n). If n is a np.array, computes Fibonacci's number for each of the elements.

    Parameters
    ----------
    n: int or np.array

    Returns
    -------
    int or np.array

    Notes
    -----
        Should not be used for numbers above 70-ish, due to this method using Binet's formula which is constrained by
        accuracy of floating point representation.
    """
    phi = (1 + np.sqrt(5)) / 2
    return np.divide(np.power(phi, n) - np.power(- phi, np.negative(n)), np.sqrt(5))


def _apply_attr(train_feats, valid_attrs, valid_thresh):
    """Returns result of applying X-of-N attribute to data set `train_feats`.

    Parameters
    ----------
    train_feats: np.array
        Data set to apply X-of-N attribute to

    valid_attrs: list or np.array
        Attributes that are used in X-of-N attribute

    valid_thresh: list or np.array
        Thresholds to go along with `valid_attrs` in X-of-N attribute

    Returns
    -------
    np.array
        Result of applying X-of-N attribute to data set. Value at index `i` represents how many conditions of X-of-N
        attribute were true in `i`-th row of `train_feats`.
    """
    if train_feats.ndim == 1:
        train_feats = np.expand_dims(train_feats, 0)

    return np.sum(np.less(train_feats[:, valid_attrs], valid_thresh), axis=1)


def _eval_attr(curr_gini, best_gini, train_feats, attr_feats, attr_thresh, available_attrs):
    """Evaluates if newly constructed X-of-N attribute achieves lower Gini index value than `best_gini`
    and returns attribute complexity in this case. Otherwise returns None

    Parameters
    ----------
    curr_gini: float
        Gini index value of current attribute

    best_gini: float
        Best gini index value encountered so far

    train_feats: np.array
        Training data set

    attr_feats: list or np.array
        Features that make up current X-of-N attribute (i.e. `xofn_attr.idx_attr` if `xofn_attr` is
        an object of type XofNAttribute)

    attr_thresh: list or np.array
        Thresholds that make up current X-of-N attribute (i.e. `xofn_attr.thresh_val` if `xofn_attr` is
        an object of type XofNAttribute)

    available_attrs: list or np.array
        Attribute indices that are available for construction of X-of-N attribute. This is often equal to
        all available features (`np.arange(train_feats.shape[1])`), but can also be a subset of that (e.g.
        a random sample of features when constructing random forests)

    Returns
    -------
    float or None
        Complexity of new attribute if new attribute is "better" or None if it is not
    """
    if curr_gini < best_gini:
        curr_compl = _calc_attr_cost(train_feats, attr_feats, attr_thresh, available_attrs=available_attrs)
        return curr_compl
    # elif np.isclose(curr_gini, best_gini):
    #     curr_compl = _calc_attr_cost(train_feats, attr_feats, attr_thresh, available_attrs=available_attrs)
    #     # complexity check
    #     # ...
    #     return curr_compl


def _calc_attr_cost(train_feats, idx_attr, thresh_val, available_attrs):
    """ Calculate new X-of-N attribute's complexity (equation 1 and 2 in paper on X-of-N trees [1]).

    Parameters
    ----------
    train_feats: np.array
        Training data set

    idx_attr: list or np.array
        Features that make up current X-of-N attribute (i.e. `xofn_attr.idx_attr` if `xofn_attr` is
        an object of type XofNAttribute)

    thresh_val: list or np.array
        Thresholds that make up current X-of-N attribute (i.e. `xofn_attr.thresh_val` if `xofn_attr` is
        an object of type XofNAttribute)

    available_attrs: list or np.array
        Attribute indices that are available for construction of X-of-N attribute. This is often equal to
        all available features (`np.arange(train_feats.shape[1])`), but can also be a subset of that (e.g.
        a random sample of features when constructing random forests)

    Returns
    -------
    float
        Cost (complexity) of attribute.

    References
    ----------
    [1] Zheng, Z. (2000). Constructing X-of-N attributes for decision tree learning.
        Machine learning, 40(1), 35-75.
    """
    if train_feats.ndim == 1:
        train_feats = np.expand_dims(train_feats, 0)

    unique_attrs_xon = np.unique(idx_attr)

    # N... number of different attributes in X-of-N attribute
    n_unique_attrs_xon = unique_attrs_xon.shape[0]
    # Na... number of primitive attrs. available for creating X-of-N attribute
    n_all_attrs = available_attrs.shape[0]
    # Nvj... number of different values of attribute j
    n_vals = np.array([np.unique(train_feats[:, i]).shape[0] for i in unique_attrs_xon])
    # nj... number of different values of attribute j that appear in X-of-N attribute
    n_unique_vals = np.array([np.unique(np.compress(np.equal(idx_attr, i), thresh_val)).shape[0]
                              for i in unique_attrs_xon])

    # log2(Na) + nj * log2(Nvj) - log2(nj!)
    cost_attr_wise = np.log2(n_all_attrs) + n_unique_vals * np.log2(n_vals) - np.log2(_fib(n_unique_vals))

    return np.sum(cost_attr_wise) - np.log2(_fib(n_unique_attrs_xon))


def _gini(class_dist, num_el):
    """ Computes gini index value.

    Parameters
    ----------
    class_dist: list or np.array
        Number of elements for each class

    num_el: int
        Number (sum) of all elements in `class_dist`

    Returns
    -------
    float
        Gini index value
    """
    return 1 - np.sum(np.square(np.divide(class_dist, num_el)))


def _res_gini_numerical(feat, target, sorted_thresholds=None):
    """ Finds lowest Gini index value and the threshold that produced it.

    Parameters
    ----------
    feat:
        Single column of a data set (i.e. values of current attribute for the entire data set)

    target: np.array
        Labels, corresponding to `feat`

    sorted_thresholds: np.array, optional
        Thresholds to be checked, need to be sorted. If None, thresholds are automatically determined from `feat`

    Returns
    -------
    (float, int):
        Best Gini index value found and index of threshold that produced it (location of best threshold in
        `sorted_thresholds`

    Note
    ----
        Assumption: works only for numerical feature values.
    """
    # how examples are distributed among classes prior to checking splits
    uniq_classes, target, class_dist = np.unique(target, return_counts=True, return_inverse=True)

    if uniq_classes.shape[0] == 1:
        # pure subset
        return 0.0, 0

    if sorted_thresholds is None:
        sorted_thresholds = _find_valid_values(feat, target)

    # sort examples (and corresponding labels) by attribute values (i.e. by thresholds)
    sort_indices = np.argsort(feat)
    sorted_feat, sorted_target = feat[sort_indices], target[sort_indices]

    idx_thresh, idx_example = 1, 0
    num_examples = sorted_feat.shape[0]
    best_gini, idx_best_thresh = 1, 0

    # distribution of elements LT/GTE current threshold
    left, left_count = np.zeros_like(class_dist), 0
    right, right_count = np.copy(class_dist), num_examples

    while idx_thresh < sorted_thresholds.shape[0]:
        if sorted_feat[idx_example] < sorted_thresholds[idx_thresh]:
            left[sorted_target[idx_example]] += 1
            right[sorted_target[idx_example]] -= 1

            left_count += 1
            right_count -= 1
            idx_example += 1
        else:
            left_prob = (left_count / num_examples)

            # calculate gini for curr threshold
            curr_gini_res = left_prob * _gini(left, left_count) + (1 - left_prob) * _gini(right, right_count)

            if curr_gini_res < 10e-6:
                # clean subset
                best_gini, idx_best_thresh = curr_gini_res, idx_thresh
                break

            if curr_gini_res < best_gini:
                best_gini, idx_best_thresh = curr_gini_res, idx_thresh

            idx_thresh += 1

    return best_gini, idx_best_thresh


def search_xofn(train_feats, train_labels, available_attrs, last_xon, op_del, available_thresh=None):
    """ Performs a single addition (when `op_del=False`) or deletion (when `op_del=True`) of an (attr, thresh) pair.

    Parameters
    ----------
    train_feats: np.array
        Training data set features

    train_labels: np.array
        Labels corresponding to `train_feats`

    available_attrs: list or np.array
        Attribute indices that are available for construction of X-of-N attribute. This is often equal to
        all available features (`np.arange(train_feats.shape[1])`), but can also be a subset of that (e.g.
        a random sample of features when constructing random forests)

    last_xon: XofNAttribute
        Last constructed X-of-N attribute prior to this call

    op_del: bool
        A flag, specifying whether deleting an attribute from `last_xon` should be performed. If False,
        insertion of a new (attribute, threshold) will be performed instead

    available_thresh: list, optional
        Thresholds that make up current X-of-N attribute (i.e. `xofn_attr.thresh_val` if `xofn_attr` is
        an object of type XofNAttribute)

    Returns
    -------
    (XOfNAttribute, float) or (None, float)
        Newly constructed attribute and achieved Gini index value if a better attribute could be constructed or
        None and a Gini index value that should be ignored (if a better attribute could not be constructed)

    """
    # somehow only a single example made it in here
    if train_feats.ndim == 1:
        train_feats = np.expand_dims(train_feats, 0)

    last_xon_vals = _apply_attr(train_feats=train_feats,
                                valid_attrs=np.array(last_xon.idx_attr),
                                valid_thresh=np.array(last_xon.thresh_val))
    splits = np.unique(last_xon_vals)
    prior_gini, ovr_best_thresh = _res_gini_numerical(feat=last_xon_vals,
                                                      target=train_labels,
                                                      sorted_thresholds=splits)

    # gini value and complexity of best newly created X-of-N attribute
    ovr_best_gini, ovr_best_compl = prior_gini, last_xon.cost
    # split point on evaluated X-of-N attributes (i.e. best split for how many conditions are true in X-of-N attr.)
    split_val = 0
    # index of attribute that should be added or deleted (depending on op_del)
    idx_best_attr = 0
    # newly constructed attribute - if it remains None, no better attribute could be constructed
    new_attr = None

    if op_del:
        # try deleting one attribute
        xon_attrs = last_xon.idx_attr
        for idx_attr in range(len(xon_attrs)):
            # take everything but (attr, val) on index `idx_attr`
            mask = np.not_equal(range(len(xon_attrs)), idx_attr)

            valid_attrs = np.compress(mask, last_xon.idx_attr)
            valid_thresh = np.compress(mask, last_xon.thresh_val)
            new_xon_vals = _apply_attr(train_feats=train_feats,
                                       valid_attrs=valid_attrs,
                                       valid_thresh=valid_thresh)
            new_xon_thresh = np.unique(new_xon_vals)
            # returns: best_gini, idx_best_thresh
            best_gini, idx_best_thresh = _res_gini_numerical(feat=new_xon_vals,
                                                             target=train_labels,
                                                             sorted_thresholds=new_xon_thresh)

            new_cost = _eval_attr(curr_gini=best_gini,
                                  best_gini=ovr_best_gini,
                                  train_feats=train_feats,
                                  attr_feats=valid_attrs,
                                  attr_thresh=valid_thresh,
                                  available_attrs=available_attrs)

            if new_cost:
                ovr_best_gini = best_gini
                split_val = new_xon_thresh[idx_best_thresh]
                idx_best_attr = idx_attr
                ovr_best_compl = new_cost

        if ovr_best_gini < prior_gini or ovr_best_compl < last_xon.cost:
            # construct new X-of-N attribute by deleting `xon_attrs[idx_best_attr]` and corresponding thresh
            mask = np.not_equal(range(len(xon_attrs)), idx_best_attr)
            new_attr = XOfNAttribute(idx_attr=np.compress(mask, last_xon.idx_attr).tolist(),
                                     thresh_val=np.compress(mask, last_xon.thresh_val).tolist(),
                                     split_val=split_val,
                                     cost=ovr_best_compl)

    else:
        for i, idx_attr in enumerate(available_attrs):
            valid_attrs = np.array(last_xon.idx_attr + [idx_attr])
            curr_attr_thresh = _find_valid_values(train_feats[:, idx_attr], train_labels) \
                if available_thresh is None else available_thresh[i]
            for thr in curr_attr_thresh:
                valid_thresh = np.array(last_xon.thresh_val + [thr])

                new_xon_vals = np.sum(train_feats[:, valid_attrs] < valid_thresh, axis=1)
                new_xon_thresh = np.unique(new_xon_vals)
                best_gini, idx_best_thresh = _res_gini_numerical(feat=new_xon_vals,
                                                                 target=train_labels,
                                                                 sorted_thresholds=new_xon_thresh)

                new_cost = _eval_attr(curr_gini=best_gini,
                                      best_gini=ovr_best_gini,
                                      train_feats=train_feats,
                                      attr_feats=valid_attrs,
                                      attr_thresh=valid_thresh,
                                      available_attrs=available_attrs)

                if new_cost:
                    ovr_best_gini = best_gini
                    split_val = new_xon_thresh[idx_best_thresh]
                    ovr_best_thresh = thr
                    ovr_best_compl = new_cost
                    idx_best_attr = idx_attr

        if ovr_best_gini < prior_gini or ovr_best_compl < last_xon.cost:
            # construct new X-of-N attribute by adding (attr, val) pair which resulted in best gini value (< prior_gini)
            new_attr = XOfNAttribute(idx_attr=(last_xon.idx_attr + [idx_best_attr]),
                                     thresh_val=(last_xon.thresh_val + [ovr_best_thresh]),
                                     split_val=split_val,
                                     cost=ovr_best_compl)

    return new_attr, ovr_best_gini


def very_greedy_construct_xofn(train_feats, train_labels, available_attrs=None, available_thresh=None):
    """ Constructs an X-of-N attribute greedily out of `available_attrs` and their best thresholds (that produce
    lowest Gini index value).

    Parameters
    ----------
    train_feats: np.array
        Training data set features

    train_labels: np.array
        Labels corresponding to `train_feats`

    available_attrs: list or np.array, optional
        Attribute indices that are available for construction of X-of-N attribute. This is often equal to
        all available features (`np.arange(train_feats.shape[1])`), but can also be a subset of that (e.g.
        a random sample of features when constructing random forests)

    Returns
    -------
    (XOfNAttribute, float)
        First attribute represents newly constructed X-of-N attribute (may consist of just 1 primitive attribute and
        corresponding threshold) and the second represents gini index obtained with new X-of-N attribute
    """
    if train_feats.ndim == 0:
        train_feats = np.expand_dims(train_feats, 0)

    if available_attrs is None:
        available_attrs = np.arange(train_feats.shape[1])

    # element at index i is best XofN attribute that consists of i attributes
    best_xons = [None]
    del_applied = [True]

    best_gini, best_thresh, idx_best_attr = 1 + 0.01, np.nan, 0
    best_compl = np.inf
    # `attr_best_thresh[i]` is the best threshold for attribute `available_attrs[i]`
    attr_best_thresh = []

    for i, idx_attr in enumerate(available_attrs):
        curr_thresh = _find_valid_values(train_feats[:, idx_attr], train_labels) if available_thresh is None else \
            available_thresh[i]
        gini, idx_thresh = _res_gini_numerical(feat=train_feats[:, idx_attr],
                                               target=train_labels,
                                               sorted_thresholds=curr_thresh)
        attr_best_thresh.append([curr_thresh[idx_thresh]])

        new_cost = _eval_attr(curr_gini=gini,
                              best_gini=best_gini,
                              train_feats=train_feats,
                              attr_feats=[idx_attr],
                              attr_thresh=curr_thresh[idx_thresh],
                              available_attrs=available_attrs)

        if new_cost:
            best_gini = gini
            best_thresh = curr_thresh[idx_thresh]
            idx_best_attr = idx_attr
            best_compl = new_cost

    best_xons.append(XOfNAttribute([idx_best_attr], [best_thresh], split_val=1, cost=best_compl))
    del_applied.append(True)  # deletion attempt would be pointless

    # length of last X-of-N attribute constructed
    len_last_xon = 1
    # number of consequent iterations in which no insertion of new (attr, val) pairs was performed
    iters_no_add = 0

    while len_last_xon > 0:
        if iters_no_add == 5:
            break
        # specifies if the algorithm should try deletion or insertion of an (attr, val) pair
        do_del = not del_applied[len_last_xon]
        new_attr, new_gini = search_xofn(train_feats=train_feats,
                                         train_labels=train_labels,
                                         available_attrs=available_attrs,
                                         available_thresh=attr_best_thresh,
                                         last_xon=best_xons[len_last_xon],
                                         op_del=do_del)

        if do_del:
            del_applied[len_last_xon] = True

            if new_attr is not None:
                # delete resulted in a better X-of-N attribute
                best_gini = new_gini
                len_last_xon -= 1
                best_xons[len_last_xon] = new_attr
                if len_last_xon > 1:
                    del_applied[len_last_xon] = False
                iters_no_add += 1
        else:
            if new_attr is None:
                # tried both deletion and insertion on current attribute, nothing resulted in a better attribute
                # print("Neither DEL nor INS produced better attribute, ending... [Best X-of-N attribute length: %d]"
                #       % len_last_xon)
                break
            else:
                iters_no_add = 0

                best_gini = new_gini
                len_last_xon += 1
                if len_last_xon >= len(best_xons):
                    best_xons.append(new_attr)
                    del_applied.append(False)
                else:
                    best_xons[len_last_xon] = new_attr
                    # del_applied[len_last_xon] = False

    return best_xons[len_last_xon], best_gini


class TreeNode(object):
    __slots__ = ('attr_list', 'thresh_list', 'split_val', 'is_leaf', 'outcome', 'probas', 'lch', 'rch')

    """
    Parameters
    ----------
    is_leaf: bool
        Specifies whether node is internal (splits data) or a leaf (contains outcome)

    Notes
    -----
        Create internal/leaf nodes using static methods TreeNode.create_leaf(...) and TreeNode.create_internal(...).
    """
    def __init__(self, is_leaf):
        self.attr_list = None
        self.thresh_list = None
        self.split_val = None
        self.is_leaf = is_leaf
        self.outcome = None
        self.probas = None
        self.lch = None
        self.rch = None

    @staticmethod
    def create_leaf(probas, outcome):
        node = TreeNode(is_leaf=True)
        node.outcome = outcome
        node.probas = probas

        return node

    @staticmethod
    def create_internal(attr_list, thresh_list, split_val, lch=None, rch=None):
        node = TreeNode(is_leaf=False)
        node.attr_list = attr_list
        node.thresh_list = thresh_list
        node.split_val = split_val
        node.lch = lch
        node.rch = rch

        return node


class XOfNTree(object):
    __slots__ = ('min_samples_leaf', 'max_features', 'max_depth', 'classes_', '_max_feats', '_min_samples',
                 'labels_encoded', '_root', '_is_fitted')
    """
    Parameters
    ----------
    min_samples_leaf: int, optional
    
    max_features: int or float or str or None, optional
        Number of features to be considered when constructing the tree:
        - if None, use all features,
        - if "auto" or "sqrt", use a random sample (without replacement) of attributes of size
        `sqrt(n_all_features)`,
        - if int, use a random sample (without replacement) of attributes of (absolute) size `max_features`,
        - if float, use a random sample (without replacement) of attributes of size `max_features * n_all_features`
        
    max_depth: int, optional
        Max depth of constructed tree. If None, uses 2 ** 30, which in most cases means fully growing a tree
    
    random_state: int, optional
        Random state for random number generator. If None, do not seed the generator
        
    labels_encoded: bool, optional
        Specifies if labels, passed to `fit(...)` are already encoded as specified by `classes_`
        WARNING: Will likely be removed from init params later on
    
    classes_: np.array, optional
        Mapping of classes to indices in outcome vectors
        WARNING: Will likely be removed from init params later on    
    """
    def __init__(self, min_samples_leaf=1,
                 max_features=None,
                 max_depth=None,
                 random_state=None,
                 labels_encoded=False,
                 classes_=None):
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.max_depth = max_depth if max_depth is not None else 2 ** 30
        self.labels_encoded = labels_encoded
        if random_state is not None:
            np.random.seed(random_state)

        self.classes_ = classes_
        self._max_feats = None
        self._min_samples = None
        self._root = None
        self._is_fitted = False

    @staticmethod
    def calc_max_feats(state, n_feats):
        if state is None:
            return n_feats
        elif isinstance(state, int):
            return state
        elif isinstance(state, float):
            return int(state * n_feats)
        elif state in ("auto", "sqrt"):
            return int(np.sqrt(n_feats))
        elif state == "log2":
            return int(np.log2(n_feats))
        else:
            raise ValueError("Invalid 'max_features' value encountered (%s)..." % str(state))

    @staticmethod
    def calc_min_samples(state, n_samples):
        if isinstance(state, int):
            return state
        elif isinstance(state, float):
            return int(state * n_samples)
        else:
            raise ValueError("Invalid 'min_samples_leaf' value encountered (%s)..." % str(state))

    def encode_labels(self, labels):
        self.classes_, enc_labels = np.unique(labels, return_inverse=True)
        return enc_labels

    def fit(self, train_feats, train_labels):
        self._is_fitted = False
        if train_feats.ndim == 1:
            train_feats = np.expand_dims(train_feats, 0)

        if not self.labels_encoded:
            train_labels = self.encode_labels(train_labels)
        self._max_feats = XOfNTree.calc_max_feats(self.max_features, train_feats.shape[1])
        self._min_samples = XOfNTree.calc_min_samples(self.min_samples_leaf, train_feats.shape[0])

        self._root = self._split_rec(train_feats, train_labels, 0)
        self._is_fitted = True

    def _split_rec(self, curr_feats, curr_labels, curr_depth):
        # Note: `curr_feats` should be 2-dim (check is handled in self.fit())
        n_attrs = curr_feats.shape[1]
        n_samples = curr_feats.shape[0]
        uniqs, class_dist = np.unique(curr_labels, return_counts=True)

        if curr_depth == self.max_depth:
            probas = np.zeros_like(self.classes_, dtype=np.float32)
            probas[uniqs] = class_dist / n_samples
            return TreeNode.create_leaf(probas, outcome=np.argmax(probas))

        if class_dist.shape[0] == 1:
            # pure subset
            probas = np.zeros_like(self.classes_, dtype=np.float32)
            probas[curr_labels[0]] = 1
            return TreeNode.create_leaf(probas, outcome=curr_labels[0])

        prior_gini = _gini(class_dist, n_samples)
        selected_attrs = np.random.choice(n_attrs, size=self._max_feats, replace=False) \
            if self._max_feats < n_attrs else np.arange(n_attrs)
        new_attr, new_gini = very_greedy_construct_xofn(curr_feats, curr_labels, available_attrs=selected_attrs)

        # if best possible constructed attribute is of length > 1 and has same gini, that means it reduces
        # representation complexity (which means the algorithm should not terminate just yet)
        if (len(new_attr) == 1 and new_gini >= prior_gini) or (len(new_attr) > 1 and new_gini > prior_gini):
            probas = np.zeros_like(self.classes_, dtype=np.float32)
            probas[uniqs] = class_dist / n_samples
            return TreeNode.create_leaf(probas, outcome=np.argmax(probas))

        # contains number of true conditions in newly created X-of-N attribute for each row in `train_feats`
        xon_vals = _apply_attr(curr_feats,
                               valid_attrs=new_attr.idx_attr,
                               valid_thresh=new_attr.thresh_val)

        node = TreeNode.create_internal(attr_list=new_attr.idx_attr,
                                        thresh_list=new_attr.thresh_val,
                                        split_val=new_attr.split_val)

        lch_mask = xon_vals < new_attr.split_val
        rch_mask = np.logical_not(lch_mask)

        lfeats, llabs = curr_feats[lch_mask, :], curr_labels[lch_mask]
        rfeats, rlabs = curr_feats[rch_mask, :], curr_labels[rch_mask]

        if llabs.shape[0] < self._min_samples or rlabs.shape[0] < self._min_samples:
            # further split would result in a node having to learn on a subset that is too small
            probas = np.zeros_like(self.classes_, dtype=np.float32)
            probas[uniqs] = class_dist / n_samples
            return TreeNode.create_leaf(probas, outcome=np.argmax(probas))

        node.lch = self._split_rec(lfeats, llabs, curr_depth + 1)
        node.rch = self._split_rec(rfeats, rlabs, curr_depth + 1)
        return node

    def predict(self, test_feats):
        return self.classes_[np.argmax(self.predict_proba(test_feats), axis=1)]

    def predict_proba(self, test_feats):
        """
        Parameters
        ----------
        test_feats: np.array

        Returns
        -------
        np.array
            Predicted probabilities for each example in `test_feats`. Probabilities are placed in the order, specified
            by `self.classes_`.
        """
        if not self._is_fitted:
            raise Exception("Model not fitted! Please call fit() first...")

        if test_feats.ndim == 1:
            test_feats = np.expand_dims(test_feats, 0)

        n_samples = test_feats.shape[0]
        return np.array([self._single_pred_proba(test_feats[idx_ex, :], self._root)
                        for idx_ex in range(n_samples)])

    def _single_pred_proba(self, single_example, curr_node):
        """
        Parameters
        ----------
        single_example: np.array
            Example for which prediction will be made.
        curr_node: TreeNode

        Returns
        -------
        np.array
            Probability predictions for `single_example`.
        """

        if curr_node.is_leaf:
            return curr_node.probas

        xon_value = _apply_attr(single_example, curr_node.attr_list, curr_node.thresh_list)

        if xon_value < curr_node.split_val:
            return self._single_pred_proba(single_example, curr_node.lch)
        else:
            return self._single_pred_proba(single_example, curr_node.rch)


# data for parallel fitting of random X-of-N forests
# READ-ONLY! (write only in main process)
_shared_data_xofn = {}


def _set_shared_data(feats, labels, shape):
    _shared_data_xofn["feats"] = feats
    _shared_data_xofn["labels"] = labels
    _shared_data_xofn["shape"] = shape


def _clear_shared_data():
    _shared_data_xofn.clear()


class RandomXOfNForest(object):
    def __init__(self, n_estimators=100,
                 min_samples_leaf=1,
                 max_features="sqrt",
                 sample_size=None,
                 max_depth=None,
                 n_jobs=1,
                 random_state=None,
                 labels_encoded=False,
                 classes_=None):
        self.n_estimators = n_estimators
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.sample_size = sample_size
        self.max_depth = max_depth
        self.n_jobs = max(1, n_jobs) if n_jobs != -1 else multiprocessing.cpu_count()
        if random_state is not None:
            np.random.seed(random_state)
        self.labels_encoded = labels_encoded
        self.classes_ = classes_

        self.estimators = []
        self._is_fitted = False
        self._sample_size = None

    @staticmethod
    def calc_sample_size(state, n_samples):
        if state is None:
            return n_samples
        elif isinstance(state, float):
            return int(state * n_samples)
        elif isinstance(state, int):
            return state
        else:
            raise ValueError("Invalid 'sample_size' value encountered (%s)..." % str(state))

    def encode_labels(self, labels):
        self.classes_, enc_labels = np.unique(labels, return_inverse=True)
        return enc_labels

    def _fit_process(self, n_trees, rand_seed):
        np.random.seed(rand_seed)
        shape = _shared_data_xofn["shape"]

        feats = np.frombuffer(_shared_data_xofn["feats"], np.float32).reshape(shape)
        labels = np.frombuffer(_shared_data_xofn["labels"], np.int32)
        n_samples = feats.shape[0]
        trees = []

        for i in range(n_trees):
            sample_idx = np.random.choice(n_samples, size=self._sample_size, replace=True)
            xofn_tree = XOfNTree(min_samples_leaf=self.min_samples_leaf,
                                 max_features=self.max_features,
                                 max_depth=self.max_depth,
                                 labels_encoded=True,
                                 classes_=self.classes_)

            xofn_tree.fit(feats[sample_idx, :], labels[sample_idx])
            trees.append(xofn_tree)

        return trees

    def fit(self, train_feats, train_labels):
        self._is_fitted = False
        self.estimators = []

        if train_feats.ndim == 1:
            train_feats = np.expand_dims(train_feats, 0)

        if not self.labels_encoded:
            train_labels = self.encode_labels(train_labels)

        n_samples = train_feats.shape[0]
        self._sample_size = RandomXOfNForest.calc_sample_size(self.sample_size, n_samples)

        # put features and labels into shared data
        feats_shape = train_feats.shape
        feats_base = multiprocessing.Array("f", feats_shape[0] * feats_shape[1], lock=False)
        feats_np = np.frombuffer(feats_base, dtype=np.float32).reshape(feats_shape)
        np.copyto(feats_np, train_feats)

        labels_base = multiprocessing.Array("I", feats_shape[0], lock=False)
        labels_np = np.frombuffer(labels_base, dtype=np.int32)
        np.copyto(labels_np, train_labels)

        with multiprocessing.Pool(processes=self.n_jobs,
                                  initializer=_set_shared_data,
                                  initargs=(feats_base, labels_base, feats_shape)) as pool:
            async_objs = []
            for idx_proc in range(self.n_jobs):
                # divide `n_estimators` between `n_jobs` processes -
                # the int() rounding of floats makes sure that work gets split as evenly as possible
                start = int(float(idx_proc) * self.n_estimators / self.n_jobs)
                end = int(float(idx_proc + 1) * self.n_estimators / self.n_jobs)

                async_objs.append(pool.apply_async(func=self._fit_process,
                                                   args=(end - start, np.random.randint(2**30))))

            res = [obj.get() for obj in async_objs]
            self.estimators = list(chain(*[ests for ests in res]))

        _clear_shared_data()
        self._is_fitted = True

    def predict_proba(self, test_feats):
        if not self._is_fitted:
            raise Exception("Model not fitted! Please call fit() first...")
        if test_feats.ndim == 1:
            test_feats = np.expand_dims(test_feats, 0)

        n_samples = test_feats.shape[0]
        proba_preds = np.zeros((n_samples, self.classes_.shape[0]), dtype=np.float32)

        for i in range(self.n_estimators):
            preds = self.estimators[i].predict_proba(test_feats)
            proba_preds += preds

        proba_preds = np.divide(proba_preds, self.n_estimators)
        return proba_preds

    def predict(self, test_feats):
        return self.classes_[np.argmax(self.predict_proba(test_feats), axis=1)]
