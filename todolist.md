1: 为什么ower Metrics  (unit: W)
mean_positive/negative_power : mean of instantaneous positive/negative samples, averaged over cycles
positive_power_ratio         : Σ(P>0) / [Σ(P>0) + Σ|P<0|]  per cycle, averaged over cycles

── L leg  (235 cycles) ──
  mean_positive_power  : +15.9960 W
  mean_negative_power  : -5.5288 W
  positive_power_ratio : 0.8947  (89.5 %)

  你这个是不是按照均值算了？理论上应该也是一秒之内的Σ(P>0)和Σ|P<0|
  另外给两种算法，一种是一个周期内，  mean_positive_power和  mean_negative_power 多少，positive_power_ratio多少。另外一个是，一秒之内mean_positive_power和  mean_negative_power 多少，positive_power_ratio多少。

  第二个事情，为什么每一次split gait cycle之后，上面的选区框框就会跳回原本的地方？而且变成初始长度？应该不管干什么上面都不变吧。

  第三个事情，计算power之前有可能还要对速度滤波一下，可以自己选择配置滤波器，就默认iir butterworth，然后自己填个截止频率？滤波完之后再去计算power，不然raw 速度输入进去太可怕了。

第四个事情，可以再生成一航新的图吗？比如右腿的四象限图，现在多一张第五行，就是，右腿，r的p（legend是residual torque），d（legend是priority torque），还有最终生成力矩放在一起。
  