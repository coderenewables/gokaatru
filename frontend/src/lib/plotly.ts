import Plotly from "plotly.js/lib/core";
import bar from "plotly.js/lib/bar";
import barpolar from "plotly.js/lib/barpolar";
import heatmap from "plotly.js/lib/heatmap";
import histogram from "plotly.js/lib/histogram";
import scatter from "plotly.js/lib/scatter";
import scattergl from "plotly.js/lib/scattergl";

Plotly.register([bar, barpolar, heatmap, histogram, scatter, scattergl]);

export { Plotly };