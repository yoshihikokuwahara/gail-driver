

import numpy as np
from rllab.misc import special
from rllab.misc import tensor_utils
from rllab.algos import util
import rllab.misc.logger as logger
import ipdb

class Sampler(object):
    def start_worker(self):
        """
        Initialize the sampler, e.g. launching parallel workers if necessary.
        """
        raise NotImplementedError

    def obtain_samples(self, itr):
        """
        Collect samples for the given iteration number.
        :param itr: Iteration number.
        :return: A list of paths.
        """
        raise NotImplementedError

    def process_samples(self, itr, paths):
        """
        Return processed sample data (typically a dictionary of concatenated tensors) based on the collected paths.
        :param itr: Iteration number.
        :param paths: A list of collected paths.
        :return: Processed sample data.
        """
        raise NotImplementedError

    def shutdown_worker(self):
        """
        Terminate workers if necessary.
        """
        raise NotImplementedError


class BaseSampler(Sampler):
    def __init__(self, algo):
        """
        :type algo: BatchPolopt
        """
        self.algo = algo

    def process_samples(self, itr, paths):
        baselines = []
        returns = []
        env_returns = []
        #ipdb.set_trace()

        if hasattr(self.algo.baseline, "predict_n"):
            all_path_baselines = self.algo.baseline.predict_n(paths)
        else:
            all_path_baselines = [
                self.algo.baseline.predict(path) for path in paths]

        for idx, path in enumerate(paths):
            path_baselines = np.append(all_path_baselines[idx], 0)
            deltas = path["rewards"] + \
                self.algo.discount * path_baselines[1:] - \
                path_baselines[:-1]
            path["advantages"] = special.discount_cumsum(
                deltas, self.algo.discount * self.algo.gae_lambda)
            path["returns"] = special.discount_cumsum(
                path["rewards"], self.algo.discount)
            baselines.append(path_baselines[:-1])
            returns.append(path["returns"])
            if path.has_key("env_rewards"):
                path["env_returns"] = special.discount_cumsum(
                    path["env_rewards"], self.algo.discount)
                env_returns.append(path["env_returns"])

        #ipdb.set_trace()
        concat_baselines = np.concatenate(baselines)
        concat_returns = np.concatenate(returns)
        ev = special.explained_variance_1d(
            concat_baselines,
            concat_returns
        )

        if not self.algo.policy.recurrent:
            observations = tensor_utils.concat_tensor_list(
                [path["observations"] for path in paths])
            actions = tensor_utils.concat_tensor_list(
                [path["actions"] for path in paths])
            rewards = tensor_utils.concat_tensor_list(
                [path["rewards"] for path in paths])
            returns = tensor_utils.concat_tensor_list(
                [path["returns"] for path in paths])
            advantages = tensor_utils.concat_tensor_list(
                [path["advantages"] for path in paths])
            env_infos = tensor_utils.concat_tensor_dict_list(
                [path["env_infos"] for path in paths])
            agent_infos = tensor_utils.concat_tensor_dict_list(
                [path["agent_infos"] for path in paths])

            env_returns = [path["env_rewards"]
                           for path in paths if path.has_key("env_rewards")]

            if self.algo.center_adv:
                advantages = util.center_advantages(advantages)

            if self.algo.positive_adv:
                advantages = util.shift_advantages_to_positive(advantages)

            average_discounted_return = \
                np.mean([path["returns"][0] for path in paths])

            average_discounted_env_return = \
                np.mean([path["env_returns"][0]
                         for path in paths if path.has_key("env_returns")])  # why zero?

            undiscounted_returns = [sum(path["rewards"]) for path in paths]
            undiscounted_env_returns = [
                sum(path["env_rewards"]) for path in paths if path.has_key("env_rewards")]

            ent = np.mean(self.algo.policy.distribution.entropy(agent_infos))

            samples_data = dict(
                observations=observations,
                actions=actions,
                rewards=rewards,
                returns=returns,
                advantages=advantages,
                env_infos=env_infos,
                agent_infos=agent_infos,
                paths=paths,
            )
        else:
            max_path_length = max([len(path["advantages"]) for path in paths])

            # make all paths the same length (pad extra advantages with 0)
            obs = [path["observations"] for path in paths]
            obs = tensor_utils.pad_tensor_n(obs, max_path_length)

            if self.algo.center_adv:
                raw_adv = np.concatenate(
                    [path["advantages"] for path in paths])
                adv_mean = np.mean(raw_adv)
                adv_std = np.std(raw_adv) + 1e-8
                adv = [(path["advantages"] - adv_mean) /
                       adv_std for path in paths]
            else:
                adv = [path["advantages"] for path in paths]

            adv = np.asarray([tensor_utils.pad_tensor(
                a, max_path_length) for a in adv])

            actions = [path["actions"] for path in paths]
            actions = tensor_utils.pad_tensor_n(actions, max_path_length)

            rewards = [path["rewards"] for path in paths]
            rewards = tensor_utils.pad_tensor_n(rewards, max_path_length)

            returns = [path["returns"] for path in paths]
            returns = tensor_utils.pad_tensor_n(returns, max_path_length)

            env_returns = [path["env_rewards"]
                           for path in paths if path.has_key("env_rewards")]
            env_returns = tensor_utils.pad_tensor_n(
                env_returns, max_path_length)

            agent_infos = [path["agent_infos"] for path in paths]
            agent_infos = tensor_utils.stack_tensor_dict_list(
                [tensor_utils.pad_tensor_dict(
                    p, max_path_length) for p in agent_infos]
            )

            env_infos = [path["env_infos"] for path in paths]
            env_infos = tensor_utils.stack_tensor_dict_list(
                [tensor_utils.pad_tensor_dict(
                    p, max_path_length) for p in env_infos]
            )

            valids = [np.ones_like(path["returns"]) for path in paths]
            valids = tensor_utils.pad_tensor_n(valids, max_path_length)

            average_discounted_return = \
                np.mean([path["returns"][0] for path in paths])

            average_discounted_env_return = \
                np.mean([path["env_returns"][0] for path in paths])

            undiscounted_returns = [sum(path["rewards"]) for path in paths]
            undiscounted_env_returns = [
                sum(path["env_rewards"]) for path in paths if path.has_key("env_rewards")]

            ent = np.sum(self.algo.policy.distribution.entropy(
                agent_infos) * valids) / np.sum(valids)

            samples_data = dict(
                observations=obs,
                actions=actions,
                advantages=adv,
                rewards=rewards,
                returns=returns,
                valids=valids,
                agent_infos=agent_infos,
                env_infos=env_infos,
                paths=paths,
            )

        logger.log("fitting baseline...")
        if hasattr(self.algo.baseline, 'fit_with_samples'):
            self.algo.baseline.fit_with_samples(paths, samples_data)
        else:
            self.algo.baseline.fit(paths)
        logger.log("fitted")

        logger.record_tabular('Iteration', itr)
        logger.record_tabular('AverageDiscountedReturn',
                              average_discounted_return)
        if not np.isnan(average_discounted_env_return):
            logger.record_tabular("AverageDiscountedEnvReturn",
                                  average_discounted_env_return)
        logger.record_tabular('AverageReturn', np.mean(undiscounted_returns))
        if not np.isnan(np.mean(undiscounted_env_returns)):
            logger.record_tabular('AverageEnvReturn',
                                  np.mean(undiscounted_env_returns))

        logger.record_tabular('ExplainedVariance', ev)
        logger.record_tabular('NumTrajs', len(paths))
        logger.record_tabular('Entropy', ent)
        logger.record_tabular('Perplexity', np.exp(ent))
        logger.record_tabular('StdReturn', np.std(undiscounted_returns))
        logger.record_tabular('MaxReturn', np.max(undiscounted_returns))
        logger.record_tabular('MinReturn', np.min(undiscounted_returns))
        logger.record_tabular('ConcatReturns', concat_returns)
        logger.record_tabular('ConcatBaselines', concat_baselines)

        if undiscounted_env_returns != []:
            logger.record_tabular(
                'StdEnvReturn', np.std(undiscounted_env_returns))
            logger.record_tabular(
                'MaxEnvReturn', np.max(undiscounted_env_returns))
            logger.record_tabular(
                'MinEnvReturn', np.min(undiscounted_env_returns))

        return samples_data
