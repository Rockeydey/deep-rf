import numpy as np
from sklearn.ensemble import RandomForestClassifier

# debug
import time

# finds (and returns) where elements of array 'first' are in array 'second'
# warning: very expensive in terms of memory!
# found at: https://stackoverflow.com/a/40449296
def find_reordering(first, second):
    return np.where(second[:, None] == first[None, :])[0]

def train_test_split(features, labels, test_size):
    """
    :param data:
    :param test_size: float between 0 and 1
    :return: (features_train, labels_train, features_test, labels_test)
    """
    return (features[:int((1 - test_size) * features.shape[0]), :], labels[:int((1 - test_size) * features.shape[0])],
            features[int((1 - test_size) * features.shape[0]):, :], labels[int((1 - test_size) * features.shape[0]):])


class GCForest:
    def __init__(self, window_sizes,
                 nrforests_layer=4,
                 ncrforests_layer=4,
                 max_cascade_depth=5,
                 n_estimators=500,
                 val_size=0.2,
                 k_cv=10,
                 random_state=None):
        """
        :param window_sizes: an integer or a list of integers, representing different window sizes in multi-grained scanning
        :param nrforests_layer: an integer, determiining the number of random forests in each layer of cascade forest
        :param ncrforests_layer: an integer, determining the number of completely (= extremely) randomized forests
                                in each layer of cascade forest
        :param max_cascade_depth: an integer, determining maximum allowed depth for training cascade forest
        :param n_estimators: number of trees in a random/completely random forest
        :param val_size: a float in the range [0, 1], determining the relative size of validation set that is used
                        during the training of gcForest
        :param k_cv: an integer, determining the number of folds in k-fold cross validation
        :param random_state: an integer determining the random state for random number generator
        """

        self.nrforests_layer = nrforests_layer
        self.ncrforests_layer = ncrforests_layer
        self.window_sizes = [window_sizes] if isinstance(window_sizes, int) else window_sizes

        self.k_cv = k_cv
        self.val_size = val_size
        self.max_cascade_depth = max_cascade_depth
        self.n_estimators = n_estimators
        self.random_state = random_state

        # will be used to store models that make up the whole cascade
        self._cascade = []
        self._num_layers = 0
        self._mg_scan_models = {}

    def _assign_labels(self, labels_train):
        self.classes_ = np.unique(labels_train)

    def fit(self, X_train, y_train):
        """ Fit gcForest to training data.
        :param X_train: training features
        :param y_train: training labels
        :return: None (in-place training)
        """

        # map classes to indices in probability vector
        self._assign_labels(y_train)

        self._mg_scan_models = {}

        # transform input features for each window size
        transformed_features = [self._mg_scan(X_train, y_train, window_size=w_size) for w_size in self.window_sizes]

        # (X_train, y_train, X_val, y_val) for each window size
        split_transformed_features = [train_test_split(feats, y_train, self.val_size) for feats in transformed_features]

        self._cascade = []
        # data split for the first window size
        curr_input_X, curr_input_y, curr_val_X, curr_val_y = split_transformed_features[0]
        prev_acc = 0

        while True:
            if self._num_layers >= self.max_cascade_depth:
                print("[fit()] Achieved max allowed depth for gcForest. Exiting...")
                break

            print("[fit()] Training layer %d..." % self._num_layers)
            curr_layer_models, new_features = self._cascade_layer(curr_input_X, curr_input_y)

            # expand new level
            self._cascade.append(curr_layer_models)
            self._num_layers += 1

            print("[fit()] Shape of new features: ")
            print(new_features.shape)

            # extract validation sets for each window size - TODO: why exactly is this in a loop?
            transformed_val_X = [quad[2] for quad in split_transformed_features]

            # check performance of cascade on validation set
            new_layer_acc = self._eval_cascade(transformed_val_X, curr_val_y)
            print("[fit()] New layer accuracy is %.3f..." % new_layer_acc)

            # if accuracy (with new layer) on validation set does not increase, remove the new layer and quit training
            if new_layer_acc <= prev_acc:
                print("[fit()] New layer accuracy (%.3f) is <= than overall best accuracy (%.3f),"
                      " therefore no more layers will be added to cascade..."
                      % (prev_acc, new_layer_acc))

                del self._cascade[-1]
                self._num_layers -= 1

                break

            print("[fit()] Setting new best accuracy to %.3f..." % new_layer_acc)
            prev_acc = new_layer_acc

            print("Picking up data for %d..." % (self._num_layers % len(self.window_sizes)))
            raw_curr_input_X, curr_input_y, curr_val_X, curr_val_y = split_transformed_features[self._num_layers %
                                                                                                len(self.window_sizes)]

            curr_input_X = np.hstack((raw_curr_input_X, new_features))

        print("[fit()] Final verdict: num_layers = %d, best accuracy obtained: %3f..." % (self._num_layers, prev_acc))

    def predict(self, X_test):
        """ Predict LABELS for test data.
        :param X_test: training features
        :return: np.ndarray of length (#rows of X_test)
        """
        transformed_features = [self._mg_scan(X_test, window_size=w_size) for w_size in self.window_sizes]
        return self._predict(transformed_features, predict_probabilities=False)

    def predict_proba(self, X_test):
        """ Predict PROBABILITIES for test data.
        :param X_test: training features
        :return: np.ndarray of shape [#rows of X_test, #labels in training data]
        """
        transformed_features = [self._mg_scan(X_test, window_size=w_size) for w_size in self.window_sizes]
        return self._predict(transformed_features, predict_probabilities=True)

    def _mg_scan(self, X, y=None, window_size=50, stride=1):
        print("[_mg_scan()] Multi-grained scanning for window size %d..." % window_size)
        # if self.classes_ is None:
        #     self._assign_labels(y)

        _t1_debug = time.perf_counter()

        slices, labels = self._slice_data(X, y, window_size, stride)

        _t2_debug = time.perf_counter()

        print("Time spent slicing: %f" % (_t2_debug - _t1_debug))

        print("Shape of slices is...")
        print(slices.shape)

        # train models on obtained slices
        if y is not None:
            print("Training completely random forest with %d trees..." % self.n_estimators)
            # completely random forest
            model_crf, feats_crf = self._get_class_distrib(slices, labels, RandomForestClassifier(n_estimators=self.n_estimators,
                                                                                                  max_depth=100,
                                                                                                  max_features=1,
                                                                                                  random_state=self.random_state,
                                                                                                  n_jobs=-1))

            print("Training random forest with %d trees..." % self.n_estimators)
            # random forest
            model_rf, feats_rf = self._get_class_distrib(slices, labels, RandomForestClassifier(n_estimators=self.n_estimators,
                                                                                                max_depth=100,
                                                                                                random_state=self.random_state,
                                                                                                n_jobs=-1))

            self._mg_scan_models[window_size] = [model_crf, model_rf]
        else:
            model_crf, model_rf = self._mg_scan_models[window_size]

            feats_crf = np.zeros((slices.shape[0], self.classes_.shape[0]), dtype=np.float32)
            feats_rf = np.zeros((slices.shape[0], self.classes_.shape[0]), dtype=np.float32)

            # reorder features to set order (self.classes_) because they might not be placed the same in sklearn's
            # classifier (an example where this might happen is when some label is not present in training set) for
            # a model (reordering is the same for both models because they were trained on same data)
            right_order = find_reordering(model_crf.classes_, self.classes_)

            feats_crf[:, right_order] = model_crf.predict_proba(slices)
            feats_rf[:, right_order] = model_rf.predict_proba(slices)

        # gather up parts of representation (consecutive rows in feats np.ndarray) for each example
        transformed_feats_crf = np.reshape(feats_crf, [X.shape[0], self.classes_.shape[0] * int(feats_crf.shape[0] / X.shape[0])])
        transformed_feats_rf = np.reshape(feats_rf, [X.shape[0], self.classes_.shape[0] * int(feats_rf.shape[0] / X.shape[0])])

        return np.concatenate((transformed_feats_crf, transformed_feats_rf), axis=1)

    def _slice_data(self, X, y, window_size, stride):

        sliced_X = []
        labels = []

        for idx_example in range(X.shape[0]):
            example = X[idx_example, :]
            # print(example)

            for idx in range(0, example.shape[0] - window_size + 1, stride):
                curr_slice = example[idx: idx + window_size]

                sliced_X.append(curr_slice)
                if y is not None:
                    labels.append(y[idx_example])

        features = np.array(sliced_X)
        labels = np.array(labels) if y is not None else None

        return features, labels

    def _predict(self, transformed_features, predict_probabilities=False):
        """ Internal method, used for making predictions (either for making predictions for new data or evaluating current
        structure).
        :param transformed_features: a list, containing features, transformed with multi-grained scanning (1 entry in list
        equals 1 window size)
        :param predict_probabilities: determines whether the returned value will be probability vectors or label vectors
        :return: either probability vectors or label vectors for each feature vector
        """
        # X_test ... list of transformed feature arrays (a new feature array for each window size)
        if self._num_layers <= 0:
            raise Exception("[predict()] Number of layers is <= 0...")

        num_labels = self.classes_.shape[0]
        curr_input = transformed_features[0]

        for idx_layer in range(self._num_layers):
            print("[predict()] Going through layer %d..." % idx_layer)
            curr_layer_models = self._cascade[idx_layer]

            new_features = np.zeros((curr_input.shape[0], (self.ncrforests_layer + self.nrforests_layer) * num_labels))

            for idx_model in range(len(curr_layer_models)):
                # reorder features to set order (self.classes_) because they might not be placed the same in sklearn's
                # classifier (an example where this might happen is when some label is not present in training set) for
                # a model (reordering is the same for both models because they were trained on same data)
                tmp = new_features[:, idx_model * num_labels: (idx_model + 1) * num_labels]
                right_order = find_reordering(curr_layer_models[idx_model].classes_, self.classes_)
                tmp[:, right_order] += curr_layer_models[idx_model].predict_proba(curr_input)

                new_features[:, idx_model * num_labels: (idx_model + 1) * num_labels] = tmp


            # last layer: get class distributions (normal procedure) and average them to obtain final distribution
            if idx_layer == self._num_layers - 1:
                print("[predict()] Got to the last level...")
                final_probs = np.zeros((curr_input.shape[0], num_labels))
                print("Created a vector for final predictions of shape...")
                print(final_probs.shape)

                for idx_model in range(len(curr_layer_models)):
                    final_probs += new_features[:, idx_model * num_labels: (idx_model + 1) * num_labels]

                final_probs = np.divide(final_probs, len(curr_layer_models))

                if predict_probabilities:
                    return final_probs
                # get most probable class
                else:
                    label_indices = np.argmax(final_probs, axis=1)
                    print("Vector of label indices has a shape of...")
                    print(label_indices.shape)
                    preds = [self.classes_[idx] for idx in label_indices]
                    return np.array(preds)

            # all but the last layer: get the input concatenated with obtained class distribution vectors
            else:
                print("[predict()] I ain't fucking leaving! Concatenating input with new features...")
                curr_input = np.hstack((transformed_features[(idx_layer + 1) % len(self.window_sizes)], new_features))

    def _eval_cascade(self, X_val, y_val):
        """ Internal method, that evaluates currently built cascade.
        :param X_val: list of validation set transformed features (possibly obtained with multiple sliding window sizes)
        :param y_val: validation set labels
        :return: accuracy of cascade
        """

        print("[_eval_cascade()] Evaluating cascade on validation data of len %d ( = number of different window sizes)" % len(X_val))

        preds = self._predict(X_val)
        cascade_acc = np.sum(preds == y_val) / y_val.shape[0]
        print("[_eval_cascade()] Evaluated cascade and got accuracy %.3f..." % cascade_acc)

        return cascade_acc

    def _cascade_layer(self, X, y):
        """ Internal method that builds a layer of cascade forest.
        :param X: input data (features)
        :param y: labels
        :return: (list of trained models for current layer, distribution vector for current layer)
        """

        num_labels = self.classes_.shape[0]
        curr_layer_models = []
        curr_layer_distributions = np.zeros((X.shape[0], (self.ncrforests_layer + self.nrforests_layer) * num_labels))

        # -- completely random forests --
        for idx_curr_forest in range(self.ncrforests_layer):
            print("Training completely random forest number %d..." % idx_curr_forest)
            # each random forest produces a (#classes)-dimensional vector of class distribution
            rf_obj = RandomForestClassifier(n_estimators=self.n_estimators,
                                            max_depth=100,
                                            max_features=1,
                                            random_state=self.random_state,
                                            n_jobs=-1)

            curr_rf, curr_class_distrib = self._get_class_distrib(X, y, rf_obj)

            curr_layer_models.append(curr_rf)
            curr_layer_distributions[:, idx_curr_forest * num_labels: (idx_curr_forest + 1) * num_labels] += \
                curr_class_distrib

        # -- random forests --
        for idx_curr_forest in range(self.nrforests_layer):
            print("Training random forest number %d..." % idx_curr_forest)
            # each random forest produces a (#classes)-dimensional vector of class distribution
            rf_obj = RandomForestClassifier(n_estimators=self.n_estimators,
                                            max_depth=100,
                                            random_state=self.random_state,
                                            n_jobs=-1)

            curr_rf, curr_class_distrib = self._get_class_distrib(X, y, rf_obj)

            curr_layer_models.append(curr_rf)
            curr_layer_distributions[:, (self.ncrforests_layer + idx_curr_forest) * num_labels:
                                        (self.ncrforests_layer + idx_curr_forest + 1) * num_labels] += curr_class_distrib

        return curr_layer_models, curr_layer_distributions

    def _get_class_distrib(self, X_train, y_train, model):
        """ Obtains class distribution of a model in a cascade layer.
        :param X_train: training data (features)
        :param y_train: training data (labels)
        :param model:
        :return: tuple, consisting of (random_forest.RandomForest model, class distribution) where
                class distribution has same number of rows as X_train and (#labels) columns
        """

        bins = self._kfold_cv(X_train.shape[0], self.k_cv)
        class_distrib = np.zeros((X_train.shape[0], self.classes_.shape[0]))

        # k-fold cross validation to obtain class distribution
        for idx_test_bin in range(self.k_cv):
            print("Doing bin %d in cross validation..." % idx_test_bin)
            curr_test_mask = (bins == idx_test_bin)
            curr_train_X, curr_train_y = X_train[np.logical_not(curr_test_mask), :], y_train[np.logical_not(curr_test_mask)]
            curr_test_X, curr_test_y = X_train[curr_test_mask, :], y_train[curr_test_mask]

            model.fit(curr_train_X, curr_train_y)

            # there might come a situation where a model does not get trained on a set which contains all classes in
            # self.classes_, in that case we need to be careful to add probabilities on right places
            right_places = find_reordering(model.classes_, self.classes_)

            # can't seem to make these arrays get broadcasted to right shapes so doing it in 2 steps
            tmp = class_distrib[curr_test_mask, :]
            tmp[:, right_places] += model.predict_proba(curr_test_X)

            class_distrib[curr_test_mask, :] = tmp

        # train a RF model on whole training set, will be placed in cascade
        model.fit(X_train, y_train)

        return model, class_distrib

    def _kfold_cv(self, num_examples, k):
        """ Prepare groups for k-fold cross validation.
        :param num_examples: number of examples in data set
        :param k: number of groups
        :return: np.array of size [1, num_examples] containing group ids ranging from 0 to k - 1.
        """

        if num_examples < k:
            raise Exception("Number of examples (num_examples=%d) is lower than number of groups in k-fold CV (k=%d)..."
                            % (num_examples, k))

        limits = np.linspace(0, num_examples, k, endpoint=False)
        bins = np.digitize(np.arange(0, num_examples), limits) - 1

        return np.random.permutation(bins)