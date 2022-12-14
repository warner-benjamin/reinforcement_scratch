# Contains code from:
# CleanRL - MIT License - Copyright (c) 2019 CleanRL developers
# EnvPool - Apache License 2.0 - Copyright (c) 2022 Garena Online Private Limited

import gym
import torch
import numpy as np

from stable_baselines3.common.vec_env import VecEnvWrapper
from stable_baselines3.common.vec_env.base_vec_env import VecEnvObs, VecEnvStepReturn

from envpool.python.protocol import EnvPool


# Modified CleanRL wrapper for stats tracking
class RecordEpisodeStatistics(gym.Wrapper):
    def __init__(self, env):
        super().__init__(env)
        self.num_envs = getattr(env, "num_envs", 1)
        self.episode_returns = None
        self.episode_lengths = None
        self.has_lives = None
        self.reset(reset_env=False)

    def reset(self, reset_env=True, **kwargs):
        self.episode_returns = np.zeros(self.num_envs, dtype=np.float32)
        self.episode_lengths = np.zeros(self.num_envs, dtype=np.int32)
        self.lives = np.zeros(self.num_envs, dtype=np.int32)
        self.returned_episode_returns = np.zeros(self.num_envs, dtype=np.float32)
        self.returned_episode_lengths = np.zeros(self.num_envs, dtype=np.int32)
        if reset_env: 
            return super().reset(**kwargs)

    def step(self, action):
        return self._record_step(*super().step(action))

    def _record_step(self, observations, rewards, dones, infos):
        if self.has_lives is None:
            self.has_lives = infos.get('lives', np.array(0)).sum() > 0
        self.episode_returns += rewards
        self.episode_lengths += 1
        self.returned_episode_returns[:] = self.episode_returns
        self.returned_episode_lengths[:] = self.episode_lengths
        if self.has_lives:
            all_lives_exhausted = infos["lives"] == 0
            self.episode_returns *= 1 - all_lives_exhausted
            self.episode_lengths *= 1 - all_lives_exhausted
        else:
            self.episode_returns *= 1 - dones
            self.episode_lengths *= 1 - dones
        infos["r"] = self.returned_episode_returns
        infos["l"] = self.returned_episode_lengths
        return observations, rewards, dones, infos



class EnvPoolRecordEpisodeStats(RecordEpisodeStatistics):
    def recv(self, reset:bool=False, return_info:bool=True):
        return self._record_step(*self.env.recv(reset, return_info))



class RecordEpisodeStatisticsTorch(gym.Wrapper):
    def __init__(self, env, device):
        super().__init__(env)
        self.num_envs = getattr(env, "num_envs", 1)
        self.device = device
        self.episode_returns = None
        self.episode_lengths = None

    def reset(self, reset_env=True, **kwargs):
        self.episode_returns = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self.episode_lengths = torch.zeros(self.num_envs, dtype=torch.int32, device=self.device)
        self.returned_episode_returns = torch.zeros(self.num_envs, dtype=torch.float32, device=self.device)
        self.returned_episode_lengths = torch.zeros(self.num_envs, dtype=torch.int32, device=self.device)
        if reset_env:
            return super().reset(**kwargs)

    def step(self, action):
        observations, rewards, dones, infos = super().step(action)
        self.episode_returns += rewards
        self.episode_lengths += 1
        self.returned_episode_returns[:] = self.episode_returns
        self.returned_episode_lengths[:] = self.episode_lengths
        self.episode_returns *= 1 - dones
        self.episode_lengths *= 1 - dones
        infos["r"] = self.returned_episode_returns
        infos["l"] = self.returned_episode_lengths
        return observations, rewards, dones, infos



# EnvPool SB3 adaptor for evaluation
class VecAdapter(VecEnvWrapper):
  """
  Convert EnvPool object to a Stable-Baselines3 (SB3) VecEnv.
  :param venv: The envpool object.
  """

  def __init__(self, venv: EnvPool):
    # Retrieve the number of environments from the config
    venv.num_envs = venv.spec.config.num_envs
    super().__init__(venv=venv)

  def step_async(self, actions: np.ndarray) -> None:
    self.actions = actions

  def reset(self) -> VecEnvObs:
    return self.venv.reset()

  def seed(self, seed:int = None) -> None:
    # You can only seed EnvPool env by calling envpool.make()
    pass

  def step_wait(self) -> VecEnvStepReturn:
    obs, rewards, dones, info_dict = self.venv.step(self.actions)
    infos = []
    # Convert dict to list of dict
    # and add terminal observation
    for i in range(self.num_envs):
      infos.append(
        {
          key: info_dict[key][i]
          for key in info_dict.keys()
          if isinstance(info_dict[key], np.ndarray)
        }
      )
      if dones[i]:
        infos[i]["terminal_observation"] = obs[i]
        obs[i] = self.venv.reset(np.array([i]))

    return obs, rewards, dones, infos