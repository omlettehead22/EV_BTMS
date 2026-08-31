function generate_thesis_figures(resultsStruct,summaryTable,P)
%GENERATE_THESIS_FIGURES Export thesis-ready figures from BTMS results.
%
% All numerical content is derived from the model itself:
%   - Geometry and heat profiles come from params_materials.m / qgen functions
%   - Time-series plots come from resAll (solver outputs)
%   - Mesh study comes from mesh_verification.csv
%   - Energy balance comes from the corrected summary table
%
% Usage:
%   [summary,resAll] = main_simulation();
%   P = params_materials();
%   generate_thesis_figures(resAll,summary,P);
%
% Or, if thesis_results/BTMS_complete_results.mat exists:
%   generate_thesis_figures
%
% Figures are written to thesis_results/figures as 300 dpi PNG files.

%% Resolve inputs
if nargin < 1 || isempty(resultsStruct)
    matPath = fullfile('thesis_results','BTMS_complete_results.mat');
    if ~isfile(matPath)
        error(['Results were not supplied and %s was not found. Run ' ...
            '[summary,resAll] = main_simulation(); first.'],matPath);
    end
    S = load(matPath);
    if ~isfield(S,'resAll')
        error('%s does not contain resAll.',matPath);
    end
    resultsStruct = S.resAll;
    if isfield(S,'summary') && (nargin < 2 || isempty(summaryTable))
        summaryTable = S.summary;
    end
    if isfield(S,'P') && (nargin < 3 || isempty(P))
        P = S.P;
    end
end

if nargin < 2 || isempty(summaryTable)
    csvPath = fullfile('thesis_results','BTMS_results_summary.csv');
    if isfile(csvPath)
        summaryTable = readtable(csvPath);
    else
        summaryTable = table();
    end
end

if nargin < 3 || isempty(P)
    % Fallback: regenerate the parameter structure from source
    P = params_materials();
end

%% Output folder and consistent light-theme styling
outDir = fullfile('thesis_results','figures');
if ~exist(outDir,'dir')
    mkdir(outDir);
end

set(groot, ...
    'defaultFigureColor','w', ...
    'defaultAxesColor','w', ...
    'defaultAxesXColor','k', ...
    'defaultAxesYColor','k', ...
    'defaultAxesZColor','k', ...
    'defaultAxesGridColor',[0.85 0.85 0.85], ...
    'defaultAxesFontName','Arial', ...
    'defaultAxesFontSize',11, ...
    'defaultTextColor','k', ...
    'defaultLineLineWidth',2);

%% Generate figures
plotModelDomain(P,outDir);
plotWorkflow(outDir);
plotHeatProfiles(P,outDir);

plotTimeSeries(resultsStruct,outDir,'Tmax', ...
    'Maximum cell temperature, ^\circC', ...
    'figure_4_1_temperature_histories.png',true);

plotTimeSeries(resultsStruct,outDir,'dTmax', ...
    'Within-cell radial temperature difference, ^\circC', ...
    'figure_4_2_radial_difference.png',false);

plotTimeSeries(resultsStruct,outDir,'phi_pcm', ...
    'Node-based PCM phase indicator, -', ...
    'figure_4_3_pcm_indicator.png',false);

plotMeshStudyFromFile(outDir);
plotEnergyBalance(summaryTable,outDir);

fprintf('\nThesis figures exported to:\n  %s\n',outDir);
fprintf(['Note: time-step convergence and PCM sensitivity figures are ' ...
    'produced by their own run scripts and are not fabricated here.\n']);
end

%% ------------------------------------------------------------------------
function plotModelDomain(P,outDir)
% Geometry is read directly from the parameter structure.

rCell = getFirstField(P, ...
    {'rcellouter','r_cell_outer','Rcell','R_cell','rCell','r1'})*1000;
rPCM = getFirstField(P, ...
    {'rpcmouter','r_pcm_outer','Rpcm','R_pcm','rPCM','r2'})*1000;
rCase = getFirstField(P, ...
    {'rcaseouter','r_case_outer','Rcase','R_case','rCase','r3'})*1000;

f = figure('Color','w','Position',[100 100 900 650]);
hold on;

rectangle('Position',[-rCase -rCase 2*rCase 2*rCase], ...
    'Curvature',[1 1], ...
    'FaceColor',[0.65 0.68 0.72], ...
    'EdgeColor','k','LineWidth',1.5);

rectangle('Position',[-rPCM -rPCM 2*rPCM 2*rPCM], ...
    'Curvature',[1 1], ...
    'FaceColor',[0.96 0.68 0.25], ...
    'EdgeColor','k','LineWidth',1.5);

rectangle('Position',[-rCell -rCell 2*rCell 2*rCell], ...
    'Curvature',[1 1], ...
    'FaceColor',[0.27 0.51 0.71], ...
    'EdgeColor','k','LineWidth',1.5);

plot([0 rCase],[0 0],'k--','LineWidth',1.3);
plot(0,0,'ko','MarkerFaceColor','k','MarkerSize',5);

text(0.3,0.5,'r = 0: symmetry', ...
    'FontWeight','bold','Color','k', ...
    'VerticalAlignment','bottom');

text(0,-rCell/2,sprintf('Cell\n0-%.0f mm',rCell), ...
    'HorizontalAlignment','center', ...
    'Color','w','FontWeight','bold','FontSize',13);

text(0,(rCell+rPCM)/2, ...
    sprintf('PCM: %.0f-%.0f mm',rCell,rPCM), ...
    'HorizontalAlignment','center', ...
    'FontWeight','bold','FontSize',12);

text(0,(rPCM+rCase)/2+0.4, ...
    sprintf('Al casing: %.0f-%.0f mm',rPCM,rCase), ...
    'HorizontalAlignment','center', ...
    'FontWeight','bold','FontSize',11);

quiver(rCase,0,5,0,0, ...
    'Color',[0.65 0.05 0.05], ...
    'LineWidth',2,'MaxHeadSize',0.8);

text(rCase+1,1.2,'External convection: h, T_\infty', ...
    'Color',[0.65 0.05 0.05],'FontWeight','bold');

axis equal;
xlim([-(rCase+5),rCase+8]);
ylim([-(rCase+2),rCase+2]);
xlabel('Horizontal position, mm');
ylabel('Vertical position, mm');
title('One-dimensional radial cell-PCM-casing model');
grid on; box on;

exportgraphics(f,fullfile(outDir,'figure_3_1_model_domain.png'), ...
    'Resolution',300,'BackgroundColor','w');
close(f);
end

%% ------------------------------------------------------------------------
function plotWorkflow(outDir)
% Conceptual diagram of the code structure (no numerical data).

f = figure('Color','w','Position',[100 100 1200 470]);
axis off;

labels = { ...
    {'Material and geometry','parameters'}, ...
    {'Scenario and heat','profile'}, ...
    {'PCM property','update'}, ...
    {'Matrix and boundary','assembly'}, ...
    {'Implicit temperature','solution'}, ...
    {'Energy and metric','post-processing'}};

n = numel(labels);
x0 = 0.025; gap = 0.018;
w = (0.95-(n-1)*gap)/n;
y = 0.40; h = 0.23;

for i = 1:n
    x = x0+(i-1)*(w+gap);
    annotation(f,'textbox',[x y w h], ...
        'String',labels{i}, ...
        'HorizontalAlignment','center', ...
        'VerticalAlignment','middle', ...
        'FontSize',11,'FontWeight','bold', ...
        'Color',[0.05 0.12 0.25], ...
        'LineWidth',1.4, ...
        'BackgroundColor',[0.92 0.96 1.00], ...
        'EdgeColor',[0.15 0.35 0.60], ...
        'FitBoxToText','off');
    if i < n
        annotation(f,'arrow', ...
            [x+w x+w+gap*0.88],[y+h/2 y+h/2], ...
            'LineWidth',1.6,'Color',[0.15 0.35 0.60]);
    end
end

annotation(f,'textbox',[0.18 0.76 0.64 0.12], ...
    'String','MATLAB simulation and post-processing workflow', ...
    'HorizontalAlignment','center','EdgeColor','none', ...
    'FontSize',17,'FontWeight','bold', ...
    'Color',[0.05 0.12 0.25]);

exportgraphics(f,fullfile(outDir,'figure_3_2_workflow.png'), ...
    'Resolution',300,'BackgroundColor','w');
close(f);
end

%% ------------------------------------------------------------------------
function plotHeatProfiles(P,outDir)
% Profiles are sampled from the same qgen functions used by the solver.

tDrive = linspace(0,P.t_end_drive,1000);
qDrive = zeros(size(tDrive));
for i = 1:numel(tDrive)
    qDrive(i) = qgen_drive(tDrive(i),P)/1000;   % kW/m^3
end

tCharge = linspace(0,P.t_end_charge,1000);
qCharge = zeros(size(tCharge));
for i = 1:numel(tCharge)
    qCharge(i) = qgen_charge(tCharge(i),P)/1000; % kW/m^3
end

yMax = 1.1*max([qDrive,qCharge]);

f = figure('Color','w','Position',[100 100 1100 430]);
tiledlayout(1,2,'TileSpacing','compact','Padding','compact');

nexttile;
plot(tDrive,qDrive,'Color',[0.10 0.42 0.68],'LineWidth',2.5);
xlim([0 P.t_end_drive]); ylim([0 yMax]);
grid on; box on;
xlabel('Time, s');
ylabel('Volumetric heat generation, kW m^{-3}');
title('Drive duty');

nexttile;
plot(tCharge,qCharge,'Color',[0.82 0.25 0.18],'LineWidth',2.5);
xlim([0 P.t_end_charge]); ylim([0 yMax]);
grid on; box on;
xlabel('Time, s');
ylabel('Volumetric heat generation, kW m^{-3}');
title('Charge duty');

sgtitle('Prescribed battery heat-generation profiles','FontWeight','bold');

exportgraphics(f,fullfile(outDir,'figure_3_3_heat_profiles.png'), ...
    'Resolution',300,'BackgroundColor','w');
close(f);
end

%% ------------------------------------------------------------------------
function plotTimeSeries(resultsStruct,outDir,fieldName,yLabel,fileName,addThreshold)
% All plotted data come directly from the solver outputs in resultsStruct.

nSc = numel(resultsStruct);
types = strings(nSc,1);
for k = 1:nSc
    if isfield(resultsStruct(k),'type')
        types(k) = lower(string(resultsStruct(k).type));
    else
        types(k) = lower(string(resultsStruct(k).name));
    end
end

isDrive  = contains(types,'drive');
isCharge = contains(types,'charge');

if ~any(isDrive) || ~any(isCharge)
    names = lower(string({resultsStruct.name}));
    isDrive  = contains(names,'drive');
    isCharge = contains(names,'charge');
end

f = figure('Color','w','Position',[100 100 1150 470]);
tiledlayout(1,2,'TileSpacing','compact','Padding','compact');

plotGroup(find(isDrive),'Drive event');
plotGroup(find(isCharge),'Charge event');

sgtitle(yLabel,'FontWeight','bold');

exportgraphics(f,fullfile(outDir,fileName), ...
    'Resolution',300,'BackgroundColor','w');
close(f);

    function plotGroup(indices,panelTitle)
        nexttile; hold on;
        for j = indices(:)'
            res = resultsStruct(j).outputs;
            if ~isfield(res,fieldName)
                warning('Field %s is missing from scenario %s.', ...
                    fieldName,string(resultsStruct(j).name));
                continue;
            end
            y = res.(fieldName)(:);
            if strcmp(fieldName,'Tmax')
                y = y-273.15;   % K to degC
            end
            plot(res.t(:),y,'LineWidth',2,'DisplayName', ...
                strrep(string(resultsStruct(j).name),'_','-'));
        end
        if addThreshold
            yline(40,'--','40^\circC project threshold', ...
                'Color',[0.75 0.1 0.1], ...
                'LineWidth',1.5, ...
                'LabelVerticalAlignment','bottom');
        end
        xlabel('Time, s');
        ylabel(yLabel);
        title(panelTitle);
        grid on; box on;
        legend('Location','best','Interpreter','none');
    end
end

%% ------------------------------------------------------------------------
function plotMeshStudyFromFile(outDir)
% Mesh values are read from the verification CSV, never hard-coded.

csvPath = fullfile('thesis_results','mesh_verification.csv');
if ~isfile(csvPath)
    csvPath = 'mesh_verification.csv';
end

if ~isfile(csvPath)
    warning(['mesh_verification.csv was not found. ' ...
        'The mesh-convergence figure was not created.']);
    return;
end

meshTable = readtable(csvPath);

% Identify columns flexibly
varNames = meshTable.Properties.VariableNames;
if all(ismember({'Nodes','PeakTemperature_C'},varNames))
    N     = meshTable.Nodes;
    Tpeak = meshTable.PeakTemperature_C;
elseif width(meshTable) >= 2
    N     = meshTable{:,1};
    Tpeak = meshTable{:,2};
else
    error('mesh_verification.csv does not contain enough columns.');
end

[N,order] = sort(N);
Tpeak = Tpeak(order);

f = figure('Color','w','Position',[100 100 760 520]);

plot(N,Tpeak,'o-', ...
    'MarkerSize',8, ...
    'MarkerFaceColor',[0.10 0.42 0.68], ...
    'Color',[0.10 0.42 0.68], ...
    'LineWidth',2);

grid on; box on;
xlabel('Number of radial nodes');
ylabel('Peak temperature, ^\circC');

if any(N == 100)
    titleText = 'Spatial-convergence study (includes production grid N = 100)';
else
    titleText = {'Available spatial-convergence study', ...
        'Production grid N = 100 still requires inclusion'};
end
title(titleText);

for i = 1:numel(N)
    text(N(i),Tpeak(i),sprintf('  %.4f^\\circC',Tpeak(i)), ...
        'VerticalAlignment','bottom','Color','k');
end

exportgraphics(f,fullfile(outDir,'figure_3_4_mesh_convergence.png'), ...
    'Resolution',300,'BackgroundColor','w');
close(f);
end

%% ------------------------------------------------------------------------
function plotEnergyBalance(summaryTable,outDir)
% Plotted only if the corrected summary contains the full energy fields.

required = {'Scenario','E_generated_kJ','E_rejected_kJ','E_stored_kJ', ...
    'CalculatedResidual_J','BalanceError_pct'};

if isempty(summaryTable) || ...
        ~all(ismember(required,summaryTable.Properties.VariableNames))
    warning(['Energy-balance figure was not created because the summary ' ...
        'table is missing one or more required columns:\n%s\n' ...
        'Rerun the corrected solver and summary pipeline first.'], ...
        strjoin(required,', '));
    return;
end

x = categorical(string(summaryTable.Scenario));
x = reordercats(x,string(summaryTable.Scenario));

energy = [summaryTable.E_generated_kJ, ...
          summaryTable.E_rejected_kJ, ...
          summaryTable.E_stored_kJ];

f = figure('Color','w','Position',[100 100 1200 700]);
tiledlayout(2,1,'TileSpacing','compact','Padding','compact');

nexttile;
bar(x,energy,'grouped');
ylabel('Event energy, kJ');
title('Generated, rejected and stored energy');
legend({'Generated','Rejected','Stored'},'Location','best');
grid on; box on;

nexttile;
yyaxis left;
bar(x,summaryTable.CalculatedResidual_J,0.55, ...
    'FaceColor',[0.85 0.33 0.10]);
ylabel('Calculated residual, J');

yyaxis right;
plot(x,summaryTable.BalanceError_pct,'ko-', ...
    'MarkerFaceColor','k','LineWidth',1.5);
ylabel('Balance error, %');
yline(0.1,'r--','0.1% project criterion','LineWidth',1.5);

xlabel('Scenario');
grid on; box on;
title('Energy residual and declared acceptance criterion');

exportgraphics(f,fullfile(outDir,'figure_4_6_energy_balance.png'), ...
    'Resolution',300,'BackgroundColor','w');
close(f);
end

function value = getFirstField(S,candidates)
%GETFIRSTFIELD Return the first matching field value, else list options.
value = [];
for i = 1:numel(candidates)
    if isfield(S,candidates{i})
        value = S.(candidates{i});
        return;
    end
end
error(['None of the expected geometry fields were found. ' ...
    'Tried: %s.\nAvailable fields in P are:\n%s'], ...
    strjoin(candidates,', '), strjoin(fieldnames(P),newline));
end