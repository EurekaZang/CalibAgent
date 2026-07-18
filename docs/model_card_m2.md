# Model card: M2 basis BLR

## Intended use

M2 predicts steady body velocity from a three-axis velocity command inside the
declared command envelope. It supports sequential Bayesian updates, diagonal
measurement covariance, predictive intervals, hypothetical covariance updates,
and task-aware active design. It is not a dynamic model and must not be used to
claim transient tracking, terrain transfer, or safety.

## Features and prior

The frozen P2 feature set is an intercept, all three affine inputs, three
pairwise products, and positive/negative hinges for each axis. Command-space
features are standardized before observations arrive. Each output axis has an
independent zero-mean Gaussian parameter prior; observation covariance is added
to the configured diagonal noise variance during each update.

## Uncertainty

The predictive covariance is diagonal. Training likelihood variance equals
configured base process noise plus the observation's command-dependent excess
measurement variance, each charged once. Held-out coverage combines posterior
epistemic variance with held-out reference covariance strictly in evaluation.
The model does not represent correlated outputs,
unmodeled dynamics, context shift, or localization failure. Those limitations
must be disclosed and are assigned to P5/P6.

## Validation gates

- sequential posterior equals the weighted batch closed form;
- covariance remains symmetric positive semidefinite and does not increase;
- serialization is prediction-preserving;
- synthetic interval coverage is reported, not assumed;
- overall and family-stratified 95% coverage must remain inside 90%-98%;
- active planning uses only covariance, commands, and task weights.
