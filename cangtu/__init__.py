# -*- coding: utf-8 -*-
"""藏图盒框架层。

这里放的是「和具体功能无关」的基础设施：异步任务、加载状态、
插件契约与加载器。各功能模块（图种／解包／幻影／抠图）不应反过来依赖它们的具体实现，
而是通过 cangtu.api.HostContext 拿到需要的能力。

成员：
  api      插件契约（PluginMeta / Plugin / HostContext）与共用小工具
  loader   插件发现、按需加载、卸载、装包、manifest
  tasks    异步执行器与加载状态
  spinner  转圈图标
"""
