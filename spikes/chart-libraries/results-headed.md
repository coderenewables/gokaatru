# Results: headed (headed)

Median [min-max] of 5 runs after 1 warm-up. Times in ms unless stated. Barrier floor (empty page): 17.5 ms.

| lib | case | first render | brush latency | highlight redraw | zoom step | heap after (MB) | heap delta (MB) | selected (library vs reference) | agree |
|---|---|---|---|---|---|---|---|---|---|
| plotly4 | timeline-1 | 455.1 [437.6-515.0] | 478.2 [465.6-554.2] | 285.7 [257.5-361.3] | 169.0 [142.4-184.3] | 88 [88-88] | 69 [69-69] | 51822 vs 51822 (range, indices computed here) | true |
| plotly4 | timeline-6 | 1218.0 [1147.2-1423.0] | 1583.9 [1527.6-2077.2] | 1184.7 [1164.8-1619.8] | 570.2 [554.3-749.3] | 416 [416-416] | 392 [392-392] | 51822 vs 51822 (range, indices computed here) | true |
| plotly4 | timeline-60-decimated | 588.8 [572.7-610.4] | 1396.1 [1375.2-1444.2] | 793.7 [696.3-852.4] | 384.1 [317.3-387.5] | 50 [50-50] | 32 [32-32] | 640 vs 640 (range, indices computed here) | true |
| plotly4 | scatter-1 | 407.0 [400.2-462.6] | 182.3 [177.3-188.3] | 325.9 [319.4-344.9] | 148.7 [144.5-150.8] | 89 [89-89] | 70 [70-70] | 53828 vs 53817 (library indices) | false |
| plotly2 | timeline-1 | 488.8 [452.1-528.1] | 486.1 [460.4-546.3] | 266.9 [263.3-276.6] | 127.4 [114.3-139.9] | 98 [98-98] | 69 [69-69] | 51822 vs 51822 (range, indices computed here) | true |
| plotly2 | timeline-6 | 1225.5 [1212.4-1244.9] | 1582.1 [1543.1-1676.7] | 1174.5 [1136.7-1249.8] | 554.7 [493.1-601.0] | 426 [426-426] | 392 [392-392] | 51822 vs 51822 (range, indices computed here) | true |
| plotly2 | timeline-60-decimated | 615.0 [590.0-634.2] | 1424.7 [1355.9-1441.0] | 745.8 [663.3-852.5] | 334.7 [309.2-405.0] | 61 [61-61] | 32 [32-32] | 640 vs 640 (range, indices computed here) | true |
| plotly2 | scatter-1 | 424.4 [410.7-429.0] | 175.8 [64.9-182.3] | 297.9 [287.2-326.0] | 122.7 [120.4-123.5] | 100 [100-100] | 70 [70-70] | 53828 vs 53817 (library indices) | false |
| echarts | timeline-1 | 122.9 [120.3-130.3] | 244.7 [225.0-276.0] | 167.7 [139.8-215.3] | 86.1 [68.6-92.0] | 37 [37-37] | 29 [29-29] | 51822 vs 51822 (range, indices computed here) | true |
| echarts | timeline-6 | 262.5 [256.1-272.0] | 1014.1 [973.3-1041.3] | 780.9 [742.3-804.6] | 323.6 [289.8-343.3] | 143 [143-144] | 131 [131-131] | 51822 vs 51822 (range, indices computed here) | true |
| echarts | timeline-60-decimated | 228.9 [221.4-284.3] | 923.1 [858.8-1035.8] | 844.2 [739.5-902.1] | 446.6 [421.8-486.8] | 85 [85-85] | 77 [77-77] | 640 vs 640 (range, indices computed here) | true |
| echarts | scatter-1 | 662.8 [605.8-703.4] | 922.4 [801.1-1028.1] | 765.7 [712.5-885.6] | 74.6 [72.0-85.2] | 33 [33-33] | 24 [24-24] | 53839 vs 53839 (range, indices computed here) | true |
| uplot | timeline-1 | 62.4 [60.3-77.2] | 19.7 [16.3-32.5] | 9.8 [8.4-12.6] | 36.9 [34.1-43.2] | 11 [11-11] | 5 [5-5] | 51822 vs 51822 (range, indices computed here) | true |
| uplot | timeline-6 | 229.7 [215.5-273.3] | 60.9 [55.6-76.1] | 511.6 [498.6-551.4] | 553.5 [502.5-641.0] | 37 [37-37] | 25 [25-25] | 51822 vs 51822 (range, indices computed here) | true |
| uplot | timeline-60-decimated | 66.6 [64.7-70.3] | 15.3 [14.6-15.6] | 14.6 [14.1-15.0] | 68.1 [64.8-73.7] | 10 [10-10] | 4 [4-4] | 640 vs 640 (range, indices computed here) | true |
| uplot | scatter-1 | 255.8 [244.1-258.1] | 50.0 [49.5-51.4] | 11.3 [9.0-12.0] | 29.8 [22.9-32.7] | 41 [41-41] | 22 [22-22] | 50301 vs 50302 (library indices) | false |

## Brush latency breakdown (median, ms)

| lib | case | pointer-up to callback | callback to indices | indices to painted | total |
|---|---|---|---|---|---|
| plotly4 | timeline-1 | 110.6 [103.6-117.2] | 1.8 [1.7-3.6] | 370.8 [360.3-433.4] | 478.2 [465.6-554.2] |
| plotly4 | timeline-6 | 8.6 [7.5-109.3] | 2.7 [2.3-6.0] | 1572.6 [1466.9-2060.4] | 1583.9 [1527.6-2077.2] |
| plotly4 | timeline-60-decimated | 14.8 [11.9-20.8] | 0.8 [0.7-1.1] | 1380.6 [1360.1-1422.3] | 1396.1 [1375.2-1444.2] |
| plotly4 | scatter-1 | 155.5 [149.4-161.9] | 0.0 [0.0-0.1] | 26.8 [26.2-28.6] | 182.3 [177.3-188.3] |
| plotly2 | timeline-1 | 108.8 [101.9-117.0] | 2.5 [2.2-2.8] | 378.4 [340.9-433.8] | 486.1 [460.4-546.3] |
| plotly2 | timeline-6 | 7.5 [7.3-108.8] | 2.3 [2.1-2.7] | 1565.2 [1533.4-1586.9] | 1582.1 [1543.1-1676.7] |
| plotly2 | timeline-60-decimated | 16.8 [13.5-18.0] | 0.7 [0.6-0.8] | 1407.2 [1341.8-1423.2] | 1424.7 [1355.9-1441.0] |
| plotly2 | scatter-1 | 148.2 [32.9-155.7] | 0.0 [0.0-0.0] | 26.6 [24.7-32.0] | 175.8 [64.9-182.3] |
| echarts | timeline-1 | 4.9 [2.4-6.1] | 2.7 [1.8-4.3] | 239.2 [219.2-266.3] | 244.7 [225.0-276.0] |
| echarts | timeline-6 | 3.2 [2.7-9.5] | 2.3 [1.9-4.8] | 1009.3 [959.0-1036.2] | 1014.1 [973.3-1041.3] |
| echarts | timeline-60-decimated | 5.4 [4.9-7.9] | 0.3 [0.3-0.5] | 916.3 [853.6-1030.1] | 923.1 [858.8-1035.8] |
| echarts | scatter-1 | 3.3 [2.0-3.8] | 4.1 [3.0-5.1] | 917.0 [793.4-1019.7] | 922.4 [801.1-1028.1] |
| uplot | timeline-1 | 1.2 [0.7-2.7] | 3.3 [1.9-4.7] | 15.2 [13.7-26.2] | 19.7 [16.3-32.5] |
| uplot | timeline-6 | 1.1 [0.7-1.2] | 2.6 [1.6-3.4] | 56.4 [52.6-71.7] | 60.9 [55.6-76.1] |
| uplot | timeline-60-decimated | 0.8 [0.7-0.9] | 0.3 [0.1-0.3] | 14.2 [13.4-14.8] | 15.3 [14.6-15.6] |
| uplot | scatter-1 | 33.0 [32.8-33.8] | 0.0 [0.0-0.1] | 16.9 [16.6-17.6] | 50.0 [49.5-51.4] |

## Data preparation (not part of render time), median ms

| lib | case | generation | decimation (60 channels) | points per channel | channels |
|---|---|---|---|---|---|
| plotly4 | timeline-1 | 94 [93-109] | n/a | 262800 | 1 |
| plotly4 | timeline-6 | 239 [201-327] | n/a | 262800 | 6 |
| plotly4 | timeline-60-decimated | 1444 [1289-1463] | 79.6 [73.9-82.9] | 3200 | 60 |
| plotly4 | scatter-1 | 121 [118-131] | n/a | 252665 | 1 |
| plotly2 | timeline-1 | 95 [81-108] | n/a | 262800 | 1 |
| plotly2 | timeline-6 | 221 [209-237] | n/a | 262800 | 6 |
| plotly2 | timeline-60-decimated | 1519 [1286-1745] | 86.1 [74.8-96.8] | 3200 | 60 |
| plotly2 | scatter-1 | 127 [116-147] | n/a | 252665 | 1 |
| echarts | timeline-1 | 87 [78-94] | n/a | 262800 | 1 |
| echarts | timeline-6 | 241 [225-272] | n/a | 262800 | 6 |
| echarts | timeline-60-decimated | 1393 [1306-1630] | 78.8 [76.8-84.3] | 3200 | 60 |
| echarts | scatter-1 | 122 [99-134] | n/a | 252665 | 1 |
| uplot | timeline-1 | 85 [76-123] | n/a | 262800 | 1 |
| uplot | timeline-6 | 262 [261-270] | n/a | 262800 | 6 |
| uplot | timeline-60-decimated | 1459 [1367-1474] | 79.8 [75.1-83.6] | 3200 | 60 |
| uplot | scatter-1 | 124 [120-137] | n/a | 252665 | 1 |

## Failures

