#include "global_reloc/map_bounds.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace global_reloc
{

namespace
{

std::string trim(const std::string &s)
{
  size_t b = 0;
  while (b < s.size() && std::isspace(static_cast<unsigned char>(s[b]))) ++b;
  size_t e = s.size();
  while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) --e;
  return s.substr(b, e - b);
}

bool readPgmSize(const std::string &pgm_path, int &width, int &height)
{
  std::ifstream in(pgm_path, std::ios::binary);
  if (!in) return false;

  std::string magic;
  if (!(in >> magic) || magic != "P5") return false;

  std::string line;
  while (std::getline(in, line))
  {
    line = trim(line);
    if (line.empty() || line[0] == '#') continue;
    std::istringstream iss(line);
    if (iss >> width >> height) return width > 0 && height > 0;
  }
  return false;
}

bool parseNumberList(const std::string &text, std::vector<double> &values)
{
  std::string normalized = text;
  std::replace(normalized.begin(), normalized.end(), ',', ' ');
  std::istringstream iss(normalized);
  double v = 0.0;
  while (iss >> v) values.push_back(v);
  return !values.empty();
}

}  // namespace

MapBounds2D loadMapBoundsFromYaml(const std::string &yaml_path)
{
  MapBounds2D out;
  std::ifstream in(yaml_path);
  if (!in) return out;

  std::string image;
  double origin_x = 0.0;
  double origin_y = 0.0;
  double resolution = 0.05;
  bool have_origin = false;

  std::string line;
  bool reading_origin = false;
  std::vector<double> origin_values;

  while (std::getline(in, line))
  {
    const std::string trimmed = trim(line);
    if (trimmed.empty() || trimmed[0] == '#') continue;

    if (reading_origin)
    {
      if (trimmed.rfind("- ", 0) == 0 || trimmed.rfind("-", 0) == 0)
      {
        std::string value = trimmed;
        if (value.rfind("- ", 0) == 0) value = trim(value.substr(2));
        else if (value[0] == '-') value = trim(value.substr(1));
        try
        {
          origin_values.push_back(std::stod(value));
        }
        catch (...)
        {
          reading_origin = false;
        }
        continue;
      }
      reading_origin = false;
    }

    if (trimmed.rfind("image:", 0) == 0)
    {
      image = trim(trimmed.substr(6));
      if (!image.empty() && image.front() == '"' && image.back() == '"')
        image = image.substr(1, image.size() - 2);
    }
    else if (trimmed.rfind("resolution:", 0) == 0)
    {
      resolution = std::stod(trim(trimmed.substr(11)));
    }
    else if (trimmed.rfind("origin:", 0) == 0)
    {
      const std::string rest = trim(trimmed.substr(7));
      origin_values.clear();
      if (!rest.empty())
      {
        auto lb = rest.find('[');
        auto rb = rest.find(']');
        if (lb != std::string::npos && rb != std::string::npos && rb > lb)
        {
          parseNumberList(rest.substr(lb + 1, rb - lb - 1), origin_values);
        }
      }
      else
      {
        reading_origin = true;
      }
    }

    if (!have_origin && origin_values.size() >= 2)
    {
      origin_x = origin_values[0];
      origin_y = origin_values[1];
      have_origin = true;
      origin_values.clear();
    }
  }

  if (!have_origin && origin_values.size() >= 2)
  {
    origin_x = origin_values[0];
    origin_y = origin_values[1];
    have_origin = true;
  }

  if (image.empty() || !have_origin || resolution <= 0.0) return out;

  const auto slash = yaml_path.find_last_of('/');
  const std::string base = (slash == std::string::npos) ? "" : yaml_path.substr(0, slash + 1);
  const std::string pgm_path = base + image;

  int width = 0;
  int height = 0;
  if (!readPgmSize(pgm_path, width, height)) return out;

  out.valid = true;
  out.resolution = resolution;
  out.min_x = origin_x;
  out.min_y = origin_y;
  out.max_x = origin_x + width * resolution;
  out.max_y = origin_y + height * resolution;
  return out;
}

}  // namespace global_reloc
