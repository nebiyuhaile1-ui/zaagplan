import io
import math
from flask import Flask, render_template, request, jsonify, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

app = Flask(__name__)

def compute_layout(panels, sheet_w=2440, sheet_h=1220, kerf=3):
    """Eenvoudig Guillotine/Shelf algoritme voor visuele nesting op platen."""
    sheets = []
    
    # Maak een platte lijst van alle losse panelen
    flat_panels = []
    for p in panels:
        qty = int(p.get('qty', 1))
        w = float(p.get('width', 0))
        h = float(p.get('height', 0))
        name = p.get('name', 'Paneel')
        for _ in range(qty):
            flat_panels.append({'name': name, 'w': w, 'h': h})
            
    # Sorteer panelen op hoogte (grootste eerst)
    flat_panels.sort(key=lambda x: max(x['w'], x['h']), reverse=True)
    
    for item in flat_panels:
        pw, ph = item['w'], item['h']
        placed = False
        
        for sheet in sheets:
            # Probeer in bestaande shelves op de plaat te passen
            for shelf in sheet['shelves']:
                if shelf['rem_w'] >= pw + kerf and shelf['height'] >= ph:
                    shelf['items'].append({
                        'name': item['name'], 'x': shelf['cur_x'], 'y': shelf['y'],
                        'w': pw, 'h': ph
                    })
                    shelf['cur_x'] += pw + kerf
                    shelf['rem_w'] -= (pw + kerf)
                    placed = True
                    break
            if placed:
                break
                
            # Maak een nieuwe shelf op deze plaat als er verticale ruimte is
            if not placed and sheet['rem_h'] >= ph + kerf:
                new_shelf = {
                    'y': sheet['cur_y'], 'height': ph,
                    'cur_x': pw + kerf, 'rem_w': sheet_w - (pw + kerf),
                    'items': [{'name': item['name'], 'x': 0, 'y': sheet['cur_y'], 'w': pw, 'h': ph}]
                }
                sheet['shelves'].append(new_shelf)
                sheet['cur_y'] += ph + kerf
                sheet['rem_h'] -= (ph + kerf)
                placed = True
                break
                
        # Geen plek op bestaande platen? Maak een nieuwe plaat aan
        if not placed:
            new_sheet = {
                'id': len(sheets) + 1,
                'cur_y': ph + kerf,
                'rem_h': sheet_h - (ph + kerf),
                'shelves': [{
                    'y': 0, 'height': ph,
                    'cur_x': pw + kerf, 'rem_w': sheet_w - (pw + kerf),
                    'items': [{'name': item['name'], 'x': 0, 'y': 0, 'w': pw, 'h': ph}]
                }]
            }
            sheets.append(new_sheet)

    # Verzamel alle geplaatste rechthoeken per plaat voor de canvas
    layout_result = []
    total_used_area = 0
    for s in sheets:
        sheet_items = []
        for shelf in s['shelves']:
            for it in shelf['items']:
                sheet_items.append(it)
                total_used_area += (it['w'] + kerf) * (it['h'] + kerf)
        layout_result.append({'sheet_id': s['id'], 'items': sheet_items})

    sheet_area = sheet_w * sheet_h
    sheets_count = max(1, len(sheets)) if flat_panels else 0
    total_provided_area = sheets_count * sheet_area
    waste_percentage = round(((total_provided_area - total_used_area) / total_provided_area) * 100, 1) if total_provided_area > 0 else 0

    return {
        'sheets': layout_result,
        'sheets_needed': sheets_count,
        'total_area_m2': round(total_used_area / 1000000, 2),
        'waste_percentage': max(0, waste_percentage)
    }

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/calculate', methods=['POST'])
def calculate():
    data = request.json or {}
    panels = data.get('panels', [])
    result = compute_layout(panels)
    return jsonify(result)

@app.route('/api/export-pdf', methods=['POST'])
def export_pdf():
    data = request.json or {}
    material = data.get('material', 'MDF 18mm')
    project_naam = data.get('project_naam', 'Mijn bouwproject')
    panels = data.get('panels', [])
    layout_data = compute_layout(panels)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1e293b'))

    story.append(Paragraph(f"ZAAGPLAN / BOUWMARKT", title_style))
    story.append(Paragraph(f"Projectnaam: {project_naam} | Materiaal: {material}", styles['Normal']))
    story.append(Paragraph(f"Benodigde platen (2440x1220mm): <b>{layout_data['sheets_needed']} plaat/platen</b> | Afval: {layout_data['waste_percentage']}%", styles['Normal']))
    story.append(Spacer(1, 15))

    data_table = [['Paneelnaam', 'Lengte (mm)', 'Breedte (mm)', 'Aantal']]
    for item in panels:
        data_table.append([
            str(item.get('name', 'Paneel')),
            str(item.get('height', 0)),
            str(item.get('width', 0)),
            str(item.get('qty', 1))
        ])

    t = Table(data_table, colWidths=[200, 100, 100, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))

    story.append(Paragraph("<b>Checklist voor de bouwmarkt:</b>", styles['Heading3']))
    story.append(Paragraph("• Houtlijm D3 Watervast<br/>• Spaanplaatschroeven 4x40mm<br/>• Schuurpapier K120", styles['Normal']))

    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Zaagplan_{project_naam}.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)