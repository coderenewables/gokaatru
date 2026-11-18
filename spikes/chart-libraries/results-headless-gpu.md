# Results: headless-gpu (headless)

Median [min-max] of 5 runs after 1 warm-up. Times in ms unless stated. Barrier floor (empty page): 16.9 ms.

| lib | case | first render | brush latency | highlight redraw | zoom step | heap after (MB) | heap delta (MB) | selected (library vs reference) | agree |
|---|---|---|---|---|---|---|---|---|---|
| plotly4 | timeline-1 | 432.3 [405.9-442.5] | 444.5 [428.4-484.6] | 275.5 [228.4-353.4] | 145.6 [117.5-172.0] | 87 [87-87] | 69 [69-69] | 51822 vs 51822 (range, indices computed here) | true |
| plotly4 | timeline-6 | 1187.9 [1119.4-1197.9] | 1606.1 [1489.0-1678.9] | 1154.6 [1102.2-1239.6] | 516.9 [502.9-578.5] | 415 [415-415] | 392 [392-392] | 51822 vs 51822 (range, indices computed here) | true |
| plotly4 | timeline-60-decimated | 525.1 [515.0-546.7] | 3037.5 [3012.4-3099.8] | 618.0 [603.6-705.5] | 275.1 [273.2-321.1] | 50 [50-50] | 32 [32-32] | 640 vs 640 (range, indices computed here) | true |
| plotly4 | scatter-1 | 400.8 [396.2-411.7] | 171.0 [64.7-208.7] | 316.2 [294.4-356.9] | 135.1 [124.1-147.8] | 89 [89-89] | 70 [70-70] | 53828 vs 53817 (library indices) | false |
| plotly2 | timeline-1 | 468.5 [450.0-481.3] | 460.1 [421.7-469.1] | 259.1 [249.7-261.7] | 108.6 [107.0-114.0] | 98 [98-98] | 69 [69-69] | 51822 vs 51822 (range, indices computed here) | true |
| plotly2 | timeline-6 | 1180.9 [1166.8-1195.4] | 1778.6 [1713.2-1806.7] | 1123.5 [1117.2-1176.2] | 527.0 [496.2-559.7] | 426 [426-426] | 392 [392-392] | 51822 vs 51822 (range, indices computed here) | true |
| plotly2 | timeline-60-decimated | 564.1 [534.6-581.5] | 3098.3 [3016.9-3324.0] | 692.1 [591.8-706.0] | 339.9 [279.8-373.5] | 60 [60-60] | 32 [32-32] | 640 vs 640 (range, indices computed here) | true |
| plotly2 | scatter-1 | 405.4 [396.2-409.7] | 71.8 [62.2-179.2] | 296.7 [273.6-305.2] | 113.6 [105.0-123.4] | 99 [99-99] | 70 [70-70] | 53828 vs 53817 (library indices) | false |
| echarts | timeline-1 | 102.8 [99.8-107.4] | 230.0 [207.8-247.9] | 188.1 [145.8-199.2] | 81.2 [64.9-98.9] | 37 [37-37] | 29 [29-29] | 51822 vs 51822 (range, indices computed here) | true |
| echarts | timeline-6 | 232.1 [226.1-238.0] | 962.8 [930.2-1014.4] | 747.7 [700.9-780.5] | 255.8 [253.8-269.7] | 143 [143-143] | 130 [130-130] | 51822 vs 51822 (range, indices computed here) | true |
| echarts | timeline-60-decimated | 241.0 [235.1-248.9] | 918.8 [890.7-1050.1] | 801.0 [747.4-808.4] | 461.0 [431.2-482.5] | 84 [84-84] | 76 [76-76] | 640 vs 640 (range, indices computed here) | true |
| echarts | scatter-1 | 638.5 [569.1-773.9] | 752.2 [708.1-772.1] | 655.2 [639.9-750.8] | 59.4 [56.8-73.5] | 32 [32-32] | 24 [24-24] | 53839 vs 53839 (range, indices computed here) | true |
| uplot | timeline-1 | 48.8 [47.1-54.6] | 24.2 [16.2-27.1] | 9.0 [8.0-11.0] | 37.5 [35.4-43.0] | 11 [11-11] | 5 [5-5] | 51822 vs 51822 (range, indices computed here) | true |
| uplot | timeline-6 | 173.8 [162.7-185.4] | 57.4 [52.1-68.0] | 503.3 [494.9-505.5] | 472.2 [464.0-548.1] | 36 [36-36] | 25 [25-25] | 51822 vs 51822 (range, indices computed here) | true |
| uplot | timeline-60-decimated | 61.2 [58.8-64.0] | 14.8 [13.3-15.3] | 14.6 [10.7-15.5] | 64.2 [59.6-65.2] | 10 [10-10] | 4 [4-4] | 640 vs 640 (range, indices computed here) | true |
| uplot | scatter-1 | 260.3 [250.8-261.8] | 46.8 [45.9-48.8] | 9.0 [7.8-14.9] | 28.6 [25.6-32.1] | 41 [41-41] | 22 [22-22] | 50301 vs 50302 (library indices) | false |

## Brush latency breakdown (median, ms)

| lib | case | pointer-up to callback | callback to indices | indices to painted | total |
|---|---|---|---|---|---|
| plotly4 | timeline-1 | 106.5 [106.2-115.4] | 3.1 [2.3-4.8] | 332.1 [319.2-373.6] | 444.5 [428.4-484.6] |
| plotly4 | timeline-6 | 112.1 [7.9-115.3] | 3.0 [2.4-3.9] | 1564.4 [1370.5-1621.8] | 1606.1 [1489.0-1678.9] |
| plotly4 | timeline-60-decimated | 117.1 [9.6-123.6] | 0.5 [0.4-1.2] | 2961.1 [2891.7-3027.5] | 3037.5 [3012.4-3099.8] |
| plotly4 | scatter-1 | 143.8 [30.8-170.9] | 0.0 [0.0-0.0] | 33.9 [24.3-44.9] | 171.0 [64.7-208.7] |
| plotly2 | timeline-1 | 105.2 [104.2-116.5] | 2.5 [1.9-4.7] | 344.2 [314.5-356.0] | 460.1 [421.7-469.1] |
| plotly2 | timeline-6 | 117.9 [115.2-137.5] | 6.1 [2.9-7.3] | 1649.5 [1589.2-1666.3] | 1778.6 [1713.2-1806.7] |
| plotly2 | timeline-60-decimated | 116.5 [109.5-130.9] | 0.6 [0.5-1.0] | 2986.8 [2906.9-3192.1] | 3098.3 [3016.9-3324.0] |
| plotly2 | scatter-1 | 31.8 [30.3-144.4] | 0.0 [0.0-0.1] | 33.2 [28.9-40.3] | 71.8 [62.2-179.2] |
| echarts | timeline-1 | 3.0 [2.6-5.3] | 1.9 [1.8-2.8] | 224.8 [202.0-243.2] | 230.0 [207.8-247.9] |
| echarts | timeline-6 | 3.1 [2.4-4.8] | 2.8 [1.8-3.8] | 958.2 [923.3-1008.5] | 962.8 [930.2-1014.4] |
| echarts | timeline-60-decimated | 5.5 [4.9-6.9] | 0.3 [0.2-0.4] | 913.6 [883.5-1043.9] | 918.8 [890.7-1050.1] |
| echarts | scatter-1 | 2.0 [2.0-2.2] | 3.0 [2.8-3.6] | 746.4 [702.6-767.2] | 752.2 [708.1-772.1] |
| uplot | timeline-1 | 1.1 [0.7-2.5] | 3.3 [1.6-4.6] | 18.4 [13.9-22.1] | 24.2 [16.2-27.1] |
| uplot | timeline-6 | 0.7 [0.6-1.1] | 2.2 [1.4-3.2] | 54.5 [50.1-63.7] | 57.4 [52.1-68.0] |
| uplot | timeline-60-decimated | 0.6 [0.5-1.4] | 0.2 [0.1-0.3] | 14.0 [11.6-14.6] | 14.8 [13.3-15.3] |
| uplot | scatter-1 | 30.6 [30.2-30.9] | 0.0 [0.0-0.0] | 16.1 [15.3-18.3] | 46.8 [45.9-48.8] |

## Data preparation (not part of render time), median ms

| lib | case | generation | decimation (60 channels) | points per channel | channels |
|---|---|---|---|---|---|
| plotly4 | timeline-1 | 66 [57-72] | n/a | 262800 | 1 |
| plotly4 | timeline-6 | 193 [181-252] | n/a | 262800 | 6 |
| plotly4 | timeline-60-decimated | 1227 [1220-1352] | 70.7 [68.9-76.8] | 3200 | 60 |
| plotly4 | scatter-1 | 107 [100-135] | n/a | 252665 | 1 |
| plotly2 | timeline-1 | 78 [75-80] | n/a | 262800 | 1 |
| plotly2 | timeline-6 | 193 [184-232] | n/a | 262800 | 6 |
| plotly2 | timeline-60-decimated | 1357 [1277-1443] | 75.7 [68.9-79.7] | 3200 | 60 |
| plotly2 | scatter-1 | 101 [100-105] | n/a | 252665 | 1 |
| echarts | timeline-1 | 65 [56-67] | n/a | 262800 | 1 |
| echarts | timeline-6 | 202 [189-203] | n/a | 262800 | 6 |
| echarts | timeline-60-decimated | 1432 [1385-1534] | 82.0 [80.0-83.6] | 3200 | 60 |
| echarts | scatter-1 | 110 [97-120] | n/a | 252665 | 1 |
| uplot | timeline-1 | 60 [58-86] | n/a | 262800 | 1 |
| uplot | timeline-6 | 170 [166-183] | n/a | 262800 | 6 |
| uplot | timeline-60-decimated | 1158 [1147-1188] | 65.7 [63.9-68.0] | 3200 | 60 |
| uplot | scatter-1 | 103 [98-105] | n/a | 252665 | 1 |

## Failures

