import React from 'react';
import {Composition} from 'remotion';
import {Explainer} from './Explainer';

export const RemotionRoot = () => (
  <Composition
    id="Explainer"
    component={Explainer}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={300}
    defaultProps={{}}
    calculateMetadata={({props}) => ({durationInFrames: props.durationInFrames || 300, fps: props.fps || 30})}
  />
);
