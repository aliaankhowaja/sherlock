import { bigFrames, bigGates, bigGraph } from './fixture'
import Gates from './Gates'
import Graph from './Graph'
import PipelineStage from './Stage'

/** `/dev/big`: the graph views on a synthetic 40-node team, to check layout, pan/zoom and colouring before real big teams exist. */
export default function BigLab() {
  const g = bigGraph()
  const { frames, labels } = bigFrames(g)
  const ran = new Set(frames.map((f) => f.node).filter((n): n is string => !!n))
  return (
    <div className="screen">
      <p className="caption"><b>Layout check</b><span>synthetic 40-node team, not real data</span></p>
      <Gates g={bigGates} />
      <div className="verdict-graph">
        <Graph graph={g} verdict />
      </div>
      <PipelineStage graph={g} frames={frames} labels={labels} relevant={ran} />
    </div>
  )
}
