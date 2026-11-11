function verification_tests()
%VERIFICATION_TESTS Basic physical and numerical checks.

P = params_materials();

tTest = 300;
toleranceT = 1e-6;

%% Test 1: uniform zero-source condition

zeroResult = run_scenario_1D(...
    P,'charge','liquid','mid',...
    P.T_coolant,tTest,0);

temperatureDeparture = max(...
    abs(zeroResult.T_hist(:)-P.T_initial));

if temperatureDeparture > toleranceT
    error('verification_tests:ZeroSourceFailure',...
        ['Zero-source test failed. Maximum departure ',...
         'from initial temperature = %.6e K.'],...
         temperatureDeparture);
end

if abs(zeroResult.E_generated) > 1e-10 || ...
   abs(zeroResult.E_rejected) > 1e-6 || ...
   abs(zeroResult.E_stored) > 1e-6

    error('verification_tests:ZeroEnergyFailure',...
        'Zero-source energy test failed.');
end

fprintf('PASS: zero-source uniform-temperature test.\n');

%% Test 2: positive heat source

positiveResult = run_scenario_1D(...
    P,'charge','liquid','mid',...
    P.T_coolant,tTest,9.4e4);

minimumTemperature = min(positiveResult.T_hist(:));

if minimumTemperature < P.T_initial-1e-6
    error('verification_tests:MinimumTemperatureFailure',...
        ['Positive-source test produced a temperature ',...
         'below the initial/coolant temperature.']);
end

if positiveResult.E_rejected < -1e-6
    error('verification_tests:HeatRejectionFailure',...
        'Positive-source test produced negative rejected energy.');
end

if any(~isfinite(positiveResult.T_hist(:)))
    error('verification_tests:NonFiniteResult',...
        'Positive-source test produced a non-finite result.');
end

fprintf('PASS: positive-source minimum-temperature test.\n');
fprintf('Positive-source balance error: %.6f %%\n',...
    positiveResult.balance_error_pct);

%% Test 3: convection ordering

hResults = zeros(3,1);

hLevels = {'low','mid','high'};

for k = 1:3
    out = run_scenario_1D(...
        P,'charge','liquid',hLevels{k},...
        P.T_coolant,tTest,9.4e4);

    hResults(k) = max(out.Tmax)-273.15;
end

if ~(hResults(1) >= hResults(2) && ...
     hResults(2) >= hResults(3))

    error('verification_tests:ConvectionOrderingFailure',...
        ['Peak temperature did not decrease monotonically ',...
         'with increasing liquid heat-transfer coefficient.']);
end

fprintf('PASS: convection-coefficient ordering test.\n');

%% Test 4: mesh sensitivity

meshSizes = [65;130;260];
meshPeaks = zeros(size(meshSizes));
meshBalance = zeros(size(meshSizes));

for k = 1:numel(meshSizes)

    Pmesh = P;
    Pmesh.Nx = meshSizes(k);

    out = run_scenario_1D(...
        Pmesh,'charge','air','high',...
        Pmesh.T_amb_mild,600,9.4e4);

    meshPeaks(k) = max(out.Tmax)-273.15;
    meshBalance(k) = out.balance_error_pct;
end

differenceFromFiner = [
    abs(meshPeaks(1)-meshPeaks(2));
    abs(meshPeaks(2)-meshPeaks(3));
    NaN
];

MeshVerification = table(...
    meshSizes,meshPeaks,differenceFromFiner,meshBalance,...
    'VariableNames',{...
    'Nx','PeakTemperature_C',...
    'DifferenceFromFiner_C',...
    'BalanceError_pct'});

disp(MeshVerification);

if ~exist('thesis_results','dir')
    mkdir('thesis_results');
end

writetable(MeshVerification,...
    fullfile('thesis_results',...
    'mesh_verification.csv'));

fprintf('Mesh-verification table exported.\n');

end