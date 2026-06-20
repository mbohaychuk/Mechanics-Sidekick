import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, LegendComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { ComposeOption } from 'echarts/core'
import type { LineSeriesOption } from 'echarts/charts'
import type { GridComponentOption, TooltipComponentOption, DataZoomComponentOption, LegendComponentOption } from 'echarts/components'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, SVGRenderer])

export type ECOption = ComposeOption<
  LineSeriesOption | GridComponentOption | TooltipComponentOption | DataZoomComponentOption | LegendComponentOption
>

export default echarts
